from flask_restful import Resource
from flask import request, jsonify, make_response
from flask_security import utils, auth_token_required, roles_required, current_user, hash_password
import os
import uuid

from controllers.database import db
from controllers.models import Department, DoctorProfile, PatientProfile, Appointment, Treatment, User
from controllers.user_datastore import user_datastore
from controllers.cache import cache_get, cache_set, cache_delete, cache_delete_pattern, get_patient_search_key, get_booked_slots_key
from datetime import datetime, date, timedelta
from celery_tasks import export_treatment_csv
from celery_config import celery_app


class DepartmentCrudAPI(Resource):
    @auth_token_required
    def get(self, department_id=None):
        if department_id:
            dept = Department.query.get(department_id)
            if not dept:
                return make_response(jsonify({'message': 'Department not found.'}), 404)
            return make_response(jsonify({'id': dept.id, 'name': dept.name, 'description': dept.description}), 200)

        departments = Department.query.all()
        response = [{'id': d.id, 'name': d.name, 'description': d.description} for d in departments]
        return make_response(jsonify(response), 200)

    @auth_token_required
    @roles_required('admin')
    def post(self):
        data = request.get_json()
        if not data:
            return make_response(jsonify({'message': 'No input data provided.'}), 400)

        name = data.get('name')
        description = data.get('description')
        if not name:
            return make_response(jsonify({'message': 'Department name is required.'}), 400)

        if Department.query.filter_by(name=name).first():
            return make_response(jsonify({'message': 'Department already exists.'}), 400)

        dept = Department(name=name, description=description)
        db.session.add(dept)
        db.session.commit()

        return make_response(jsonify({'message': 'Department created.', 'data': {'id': dept.id, 'name': dept.name, 'description': dept.description}}), 201)

    @auth_token_required
    @roles_required('admin')
    def put(self, department_id):
        dept = Department.query.get(department_id)
        if not dept:
            return make_response(jsonify({'message': 'Department not found.'}), 404)

        data = request.get_json() or {}
        name = data.get('name')
        description = data.get('description')

        if name:
            other = Department.query.filter_by(name=name).first()
            if other and other.id != department_id:
                return make_response(jsonify({'message': 'Department name already exists.'}), 400)
            dept.name = name
        if description is not None:
            dept.description = description

        db.session.commit()
        return make_response(jsonify({'message': 'Department updated.', 'data': {'id': dept.id, 'name': dept.name, 'description': dept.description}}), 200)

    @auth_token_required
    @roles_required('admin')
    def delete(self, department_id):
        dept = Department.query.get(department_id)
        if not dept:
            return make_response(jsonify({'message': 'Department not found.'}), 404)

        # Prevent deleting a department if there are doctors assigned
        if dept.doctors and len(dept.doctors) > 0:
            return make_response(jsonify({'message': 'Cannot delete department with assigned doctors.'}), 400)

        db.session.delete(dept)
        db.session.commit()
        return make_response(jsonify({'message': 'Department deleted.'}), 200)


class DoctorCrudAPI(Resource):
    @auth_token_required
    def get(self, doctor_id=None):
        if doctor_id:
            doc = DoctorProfile.query.get(doctor_id)
            if not doc:
                return make_response(jsonify({'message': 'Doctor not found.'}), 404)
            # Allow archived doctors to be visible (especially for appointments)
            dept_name = doc.department.name if doc.department else None
            # include active status of linked user
            user = User.query.get(doc.user_id)
            active = user.active if user else True
            return make_response(jsonify({'id': doc.id, 'user_id': doc.user_id, 'name': doc.name, 'specialization': doc.specialization, 'contact': doc.contact, 'department_id': doc.department_id, 'department_name': dept_name, 'active': active}), 200)

        specialization = request.args.get('specialization')
        department_name = request.args.get('department_name')
        doctor_name = request.args.get('doctor_name')
        include_archived = request.args.get('include_archived', 'false').lower() == 'true'
        
        query = DoctorProfile.query
        if specialization:
            query = query.filter(DoctorProfile.specialization.ilike(f"%{specialization}%"))
        if department_name:
            query = query.join(Department).filter(Department.name.ilike(f"%{department_name}%"))
        if doctor_name:
            query = query.filter(DoctorProfile.name.ilike(f"%{doctor_name}%"))
        
        # Exclude archived doctors by default (those with [ARCHIVED] prefix in name)
        if not include_archived:
            query = query.filter(~DoctorProfile.name.ilike(f"[ARCHIVED]%"))
        
        doctors = query.all()
        response = []
        for d in doctors:
            user = User.query.get(d.user_id)
            active = user.active if user else True
            response.append({'id': d.id, 'user_id': d.user_id, 'name': d.name, 'specialization': d.specialization, 'contact': d.contact, 'department_id': d.department_id, 'department_name': d.department.name if d.department else None, 'active': active})
        return make_response(jsonify(response), 200)

    @auth_token_required
    @roles_required('admin')
    def post(self):
        # Admin creates a doctor: either provide existing user_id or email+password
        data = request.get_json()
        if not data:
            return make_response(jsonify({'message': 'No input data provided.'}), 400)

        user_id = data.get('user_id')
        email = data.get('email')
        password = data.get('password')
        name = data.get('name')
        specialization = data.get('specialization')
        contact = data.get('contact')
        department_id = data.get('department_id')

        if not name or not specialization:
            return make_response(jsonify({'message': 'name and specialization are required.'}), 400)

        if user_id:
            if not User.query.get(user_id):
                return make_response(jsonify({'message': 'User not found.'}), 404)
            if DoctorProfile.query.filter_by(user_id=user_id).first():
                return make_response(jsonify({'message': 'Doctor profile for this user already exists.'}), 400)
            doc = DoctorProfile(user_id=user_id, name=name, specialization=specialization, contact=contact, department_id=department_id)
            db.session.add(doc)
            db.session.commit()
            return make_response(jsonify({'message': 'Doctor profile created.', 'data': {'id': doc.id}}), 201)

        if not email or not password:
            return make_response(jsonify({'message': 'Either user_id or email+password must be provided.'}), 400)

        if user_datastore.find_user(email=email):
            return make_response(jsonify({'message': 'User with this email already exists.'}), 400)

        doctor_role = user_datastore.find_or_create_role(name='doctor', description='Doctor')
        new_user = user_datastore.create_user(email=email, roles=[doctor_role])
        new_user.password = hash_password(password)
        db.session.add(new_user)
        db.session.commit()

        doc = DoctorProfile(user_id=new_user.id, name=name, specialization=specialization, contact=contact, department_id=department_id)
        db.session.add(doc)
        db.session.commit()
        return make_response(jsonify({'message': 'Doctor user and profile created.', 'data': {'id': doc.id, 'user_id': new_user.id}}), 201)

    @auth_token_required
    @roles_required('admin')
    def put(self, doctor_id):
        doc = DoctorProfile.query.get(doctor_id)
        if not doc:
            return make_response(jsonify({'message': 'Doctor not found.'}), 404)

        data = request.get_json() or {}
        name = data.get('name')
        specialization = data.get('specialization')
        contact = data.get('contact')
        department_id = data.get('department_id')

        if name:
            doc.name = name
        if specialization:
            doc.specialization = specialization
        if contact is not None:
            doc.contact = contact
        if department_id is not None:
            doc.department_id = department_id

        # allow admin to toggle active status of the associated user
        active = data.get('active')
        if active is not None:
            user = User.query.get(doc.user_id)
            if user:
                user.active = bool(active)
                db.session.add(user)

        db.session.commit()
        return make_response(jsonify({'message': 'Doctor updated.'}), 200)

    @auth_token_required
    @roles_required('admin')
    def delete(self, doctor_id):
        doc = DoctorProfile.query.get(doctor_id)
        if not doc:
            return make_response(jsonify({'message': 'Doctor not found.'}), 404)
        
        # Soft delete: Preserve doctor name and related appointments for history/understanding
        # Mark associated user as inactive so login is prevented
        user = User.query.get(doc.user_id)
        if user:
            user.active = False
        
        # Add a flag or prefix to indicate deleted status - but preserve the actual name
        # Store original name if not already marked
        if not doc.name.startswith('[ARCHIVED] '):
            doc.name = f"[ARCHIVED] {doc.name}"

        db.session.commit()
        return make_response(jsonify({'message': 'Doctor deleted. Doctor name preserved for appointment records.'}), 200)


class DoctorMeAPI(Resource):
    @auth_token_required
    def get(self):
        if not current_user.has_role('doctor'):
            return make_response(jsonify({'message': 'Not a doctor.'}), 403)
        doc = DoctorProfile.query.filter_by(user_id=current_user.id).first()
        if not doc:
            return make_response(jsonify({'message': 'Doctor profile not found.'}), 404)
        dept_name = doc.department.name if doc.department else None
        return make_response(jsonify({'id': doc.id, 'user_id': doc.user_id, 'name': doc.name, 'specialization': doc.specialization, 'contact': doc.contact, 'department_id': doc.department_id, 'department_name': dept_name}), 200)


class PatientMeAPI(Resource):
    @auth_token_required
    def get(self):
        if not current_user.has_role('patient'):
            return make_response(jsonify({'message': 'Not a patient.'}), 403)
        patient = PatientProfile.query.filter_by(user_id=current_user.id).first()
        if not patient:
            return make_response(jsonify({'message': 'Patient profile not found.'}), 404)
        return make_response(jsonify({'id': patient.id, 'user_id': patient.user_id, 'name': patient.name, 'age': patient.age, 'gender': patient.gender, 'contact': patient.contact, 'address': patient.address}), 200)


class PatientCrudAPI(Resource):
    @auth_token_required
    def get(self, patient_id=None):
        if patient_id:
            patient = PatientProfile.query.get(patient_id)
            if not patient:
                return make_response(jsonify({'message': 'Patient not found.'}), 404)
            user = User.query.get(patient.user_id)
            active = user.active if user else True
            return make_response(jsonify({'id': patient.id, 'user_id': patient.user_id, 'name': patient.name, 'age': patient.age, 'gender': patient.gender, 'contact': patient.contact, 'address': patient.address, 'active': active}), 200)

        name = request.args.get('name')
        
        # Check cache first for search results
        cache_key = get_patient_search_key(name)
        cached_result = cache_get(cache_key)
        if cached_result is not None:
            return make_response(jsonify(cached_result), 200)
        
        query = PatientProfile.query
        if name:
            query = query.filter(PatientProfile.name.ilike(f"%{name}%"))
        patients = query.all()
        response = []
        for p in patients:
            user = User.query.get(p.user_id)
            active = user.active if user else True
            response.append({'id': p.id, 'user_id': p.user_id, 'name': p.name, 'age': p.age, 'gender': p.gender, 'contact': p.contact, 'address': p.address, 'active': active})
        
        # Cache the results for 5 minutes (300 seconds)
        cache_set(cache_key, response, expire_seconds=300)
        
        return make_response(jsonify(response), 200)

    @auth_token_required
    def put(self, patient_id):
        patient = PatientProfile.query.get(patient_id)
        if not patient:
            return make_response(jsonify({'message': 'Patient not found.'}), 404)
        # Allow admin to update any patient; allow a patient to update their own profile
        if current_user.has_role('admin'):
            pass
        elif current_user.has_role('patient'):
            my_patient = PatientProfile.query.filter_by(user_id=current_user.id).first()
            if not my_patient or my_patient.id != patient.id:
                return make_response(jsonify({'message': 'Not authorized to update this patient.'}), 403)
        else:
            return make_response(jsonify({'message': 'Not authorized to update patient.'}), 403)

        data = request.get_json() or {}
        name = data.get('name')
        age = data.get('age')
        gender = data.get('gender')
        contact = data.get('contact')
        address = data.get('address')

        if name:
            patient.name = name
        if age is not None:
            patient.age = age
        if gender is not None:
            patient.gender = gender
        if contact is not None:
            patient.contact = contact
        if address is not None:
            patient.address = address

        # If admin provided active flag, update associated user active status
        if current_user.has_role('admin'):
            active = data.get('active')
            if active is not None:
                user = User.query.get(patient.user_id)
                if user:
                    user.active = bool(active)
                    db.session.add(user)

        db.session.commit()
        
        # Invalidate all patient search caches since data changed
        cache_delete_pattern("patients:search:*")
        cache_delete("patients:all")
        
        return make_response(jsonify({'message': 'Patient updated.'}), 200)

    @auth_token_required
    @roles_required('admin')
    def delete(self, patient_id):
        patient = PatientProfile.query.get(patient_id)
        if not patient:
            return make_response(jsonify({'message': 'Patient not found.'}), 404)

        # Soft delete: Preserve appointments and treatments but mark user as inactive
        # Delete associated User account but keep PatientProfile and appointments
        user = User.query.get(patient.user_id)
        if user:
            user.active = False
            db.session.add(user)

        # Keep patient profile for now (can be marked as deleted later if needed)
        # Just mark the user as inactive so login is prevented
        db.session.commit()
        
        # Invalidate all patient search caches since data changed
        cache_delete_pattern("patients:search:*")
        cache_delete("patients:all")
        
        return make_response(jsonify({'message': 'Patient account deleted (appointments and treatments preserved).'}), 200)


class AppointmentAPI(Resource):
    @auth_token_required
    def get(self, appointment_id=None):
        # admin: all, doctor: own, patient: own
        if appointment_id:
            appt = Appointment.query.get(appointment_id)
            if not appt:
                return make_response(jsonify({'message': 'Appointment not found.'}), 404)
            # Build response with doctor and patient info for admin
            doctor = DoctorProfile.query.get(appt.doctor_id)
            patient = PatientProfile.query.get(appt.patient_id)
            return make_response(jsonify({
                'id': appt.id, 
                'date': appt.date.isoformat(), 
                'time': appt.time.strftime('%H:%M'), 
                'status': appt.status, 
                'doctor_id': appt.doctor_id,
                'doctor_name': doctor.name if doctor else 'N/A',
                'patient_id': appt.patient_id,
                'patient_name': patient.name if patient else 'N/A',
                'rescheduled_from_id': appt.rescheduled_from_id
            }), 200)

        if current_user.has_role('admin'):
            appts = Appointment.query.all()
        elif current_user.has_role('doctor'):
            doctor = DoctorProfile.query.filter_by(user_id=current_user.id).first()
            if not doctor:
                return make_response(jsonify({'message': 'Doctor profile not found for user.'}), 404)
            appts = Appointment.query.filter_by(doctor_id=doctor.id).all()
        else:
            # patient
            patient = PatientProfile.query.filter_by(user_id=current_user.id).first()
            if not patient:
                return make_response(jsonify({'message': 'Patient profile not found for user.'}), 404)
            appts = Appointment.query.filter_by(patient_id=patient.id).all()

        response = []
        for a in appts:
            doctor = DoctorProfile.query.get(a.doctor_id)
            patient = PatientProfile.query.get(a.patient_id)
            response.append({
                'id': a.id, 
                'date': a.date.isoformat(), 
                'time': a.time.strftime('%H:%M'), 
                'status': a.status, 
                'doctor_id': a.doctor_id,
                'doctor_name': doctor.name if doctor else 'N/A',
                'patient_id': a.patient_id,
                'patient_name': patient.name if patient else 'N/A',
                'rescheduled_from_id': a.rescheduled_from_id
            })
        return make_response(jsonify(response), 200)

    @auth_token_required
    @roles_required('patient')
    def post(self):
        data = request.get_json()
        if not data:
            return make_response(jsonify({'message': 'No input data provided.'}), 400)

        doctor_id = data.get('doctor_id')
        date_str = data.get('date')
        time_str = data.get('time')

        if not doctor_id or not date_str or not time_str:
            return make_response(jsonify({'message': 'doctor_id, date and time are required.'}), 400)

        try:
            date_obj = datetime.fromisoformat(date_str).date()
        except Exception:
            return make_response(jsonify({'message': 'Invalid date format. Use YYYY-MM-DD.'}), 400)

        try:
            time_obj = datetime.strptime(time_str, '%H:%M').time()
        except Exception:
            return make_response(jsonify({'message': 'Invalid time format. Use HH:MM.'}), 400)

        # check doctor exists
        doc = DoctorProfile.query.get(doctor_id)
        if not doc:
            return make_response(jsonify({'message': 'Doctor not found.'}), 404)

        # patient
        patient = PatientProfile.query.filter_by(user_id=current_user.id).first()
        if not patient:
            return make_response(jsonify({'message': 'Patient profile not found for user.'}), 404)

        # slot clash - only check active appointments
        existing = Appointment.query.filter_by(doctor_id=doctor_id, date=date_obj, time=time_obj, status='Booked').first()
        if existing:
            return make_response(jsonify({'message': 'Time slot already booked.'}), 400)

        appt = Appointment(patient_id=patient.id, doctor_id=doctor_id, date=date_obj, time=time_obj, status='Booked')
        db.session.add(appt)
        db.session.commit()
        
        # Invalidate booked slots cache for this doctor
        cache_delete(get_booked_slots_key(doctor_id))
        
        return make_response(jsonify({'message': 'Appointment booked.', 'data': {'id': appt.id}}), 201)

    @auth_token_required
    def put(self, appointment_id):
        appt = Appointment.query.get(appointment_id)
        if not appt:
            return make_response(jsonify({'message': 'Appointment not found.'}), 404)

        data = request.get_json() or {}
        status = data.get('status')
        date_str = data.get('date')
        time_str = data.get('time')
        
        # Check authorization: Patients can reschedule/cancel their own, Doctors can update their own, Admins can update any
        if current_user.has_role('patient'):
            patient = PatientProfile.query.filter_by(user_id=current_user.id).first()
            if not patient or appt.patient_id != patient.id:
                return make_response(jsonify({'message': 'Not authorized to modify this appointment.'}), 403)
        elif current_user.has_role('doctor'):
            doctor = DoctorProfile.query.filter_by(user_id=current_user.id).first()
            if not doctor or appt.doctor_id != doctor.id:
                return make_response(jsonify({'message': 'Not authorized to modify this appointment.'}), 403)
        elif current_user.has_role('admin'):
            pass
        else:
            return make_response(jsonify({'message': 'Not authorized to modify this appointment.'}), 403)

        # Handle reschedule: date and time provided
        if date_str and time_str:
            try:
                date_obj = datetime.fromisoformat(date_str).date()
                time_obj = datetime.strptime(time_str, '%H:%M').time()
            except Exception:
                return make_response(jsonify({'message': 'Invalid date or time format.'}), 400)
            
            # Check for slot clash (only active appointments)
            existing = Appointment.query.filter(
                Appointment.doctor_id == appt.doctor_id,
                Appointment.date == date_obj,
                Appointment.time == time_obj,
                Appointment.status.in_(['Booked', 'Completed']),
                Appointment.id != appointment_id
            ).first()
            if existing:
                return make_response(jsonify({'message': 'Time slot already booked.'}), 400)
            
            # Create new appointment with rescheduled_from link
            new_appt = Appointment(
                patient_id=appt.patient_id,
                doctor_id=appt.doctor_id,
                date=date_obj,
                time=time_obj,
                status='Booked',
                rescheduled_from_id=appointment_id
            )
            # Mark old appointment as Rescheduled
            appt.status = 'Rescheduled'
            db.session.add(new_appt)
            db.session.commit()
            
            # Invalidate booked slots cache for this doctor
            cache_delete(get_booked_slots_key(appt.doctor_id))
            
            return make_response(jsonify({'message': 'Appointment rescheduled.', 'data': {'id': new_appt.id}}), 201)
        
        # Handle status update
        if status:
            if status not in ('Completed', 'Cancelled', 'Rescheduled'):
                return make_response(jsonify({'message': 'Invalid status. Use Completed, Cancelled, or Rescheduled.'}), 400)
            appt.status = status
            db.session.commit()
            
            # Invalidate booked slots cache for this doctor when status changes
            cache_delete(get_booked_slots_key(appt.doctor_id))
            
            return make_response(jsonify({'message': 'Appointment updated.'}), 200)
        
        return make_response(jsonify({'message': 'No update fields provided.'}), 400)

    @auth_token_required
    def delete(self, appointment_id):
        appt = Appointment.query.get(appointment_id)
        if not appt:
            return make_response(jsonify({'message': 'Appointment not found.'}), 404)

        # Patients can cancel their own; admins can cancel any
        if current_user.has_role('patient'):
            patient = PatientProfile.query.filter_by(user_id=current_user.id).first()
            if not patient or appt.patient_id != patient.id:
                return make_response(jsonify({'message': 'Not authorized to cancel this appointment.'}), 403)
        elif current_user.has_role('admin'):
            pass
        else:
            return make_response(jsonify({'message': 'Not authorized to cancel this appointment.'}), 403)

        appt.status = 'Cancelled'
        db.session.commit()
        
        # Invalidate booked slots cache for this doctor
        cache_delete(get_booked_slots_key(appt.doctor_id))
        
        return make_response(jsonify({'message': 'Appointment cancelled.'}), 200)


class BookedSlotsAPI(Resource):
    """
    API endpoint to get all booked slots for a doctor.
    Returns list of booked date-time pairs for all patients.
    Used by frontend to gray out booked slots for all users.
    Implements caching for performance optimization.
    """
    @auth_token_required
    def get(self):
        doctor_id = request.args.get('doctor_id')
        if not doctor_id:
            return make_response(jsonify({'message': 'doctor_id parameter is required.'}), 400)
        
        try:
            doctor_id = int(doctor_id)
        except ValueError:
            return make_response(jsonify({'message': 'doctor_id must be an integer.'}), 400)
        
        # Check cache first
        cache_key = get_booked_slots_key(doctor_id)
        cached_result = cache_get(cache_key)
        if cached_result is not None:
            return make_response(jsonify(cached_result), 200)
        
        # Get all 'Booked' and 'Completed' appointments for this doctor across all patients
        # These statuses block time slots from being re-booked
        booked_appointments = Appointment.query.filter(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(['Booked', 'Completed'])
        ).all()
        
        # Build response with date-time pairs
        booked_slots = []
        for appt in booked_appointments:
            booked_slots.append({
                'date': appt.date.isoformat(),
                'time': appt.time.strftime('%H:%M')
            })
        
        # Cache the results for 10 minutes (600 seconds) since slots change less frequently
        cache_set(cache_key, booked_slots, expire_seconds=600)
        
        return make_response(jsonify(booked_slots), 200)


class TreatmentAPI(Resource):
    @auth_token_required
    def get(self, appointment_id):
        appt = Appointment.query.get(appointment_id)
        if not appt:
            return make_response(jsonify({'message': 'Appointment not found.'}), 404)

        treatment = Treatment.query.filter_by(appointment_id=appointment_id).first()
        if not treatment:
            return make_response(jsonify({'message': 'Treatment not found.'}), 404)

        return make_response(jsonify({'appointment_id': treatment.appointment_id, 'diagnosis': treatment.diagnosis, 'prescription': treatment.prescription, 'notes': treatment.notes}), 200)

    @auth_token_required
    @roles_required('doctor')
    def post(self, appointment_id):
        appt = Appointment.query.get(appointment_id)
        if not appt:
            return make_response(jsonify({'message': 'Appointment not found.'}), 404)

        doctor = DoctorProfile.query.filter_by(user_id=current_user.id).first()
        if not doctor or appt.doctor_id != doctor.id:
            return make_response(jsonify({'message': 'Not authorized to add treatment for this appointment.'}), 403)

        data = request.get_json() or {}
        diagnosis = data.get('diagnosis')
        prescription = data.get('prescription')
        notes = data.get('notes')

        if not diagnosis and not prescription:
            return make_response(jsonify({'message': 'At least diagnosis or prescription is required.'}), 400)

        treatment = Treatment.query.filter_by(appointment_id=appointment_id).first()
        if not treatment:
            treatment = Treatment(appointment_id=appointment_id, diagnosis=diagnosis, prescription=prescription, notes=notes)
            db.session.add(treatment)
        else:
            treatment.diagnosis = diagnosis
            treatment.prescription = prescription
            treatment.notes = notes

        db.session.commit()
        return make_response(jsonify({'message': 'Treatment saved.'}), 201)

    @auth_token_required
    def put(self, appointment_id):
        appt = Appointment.query.get(appointment_id)
        if not appt:
            return make_response(jsonify({'message': 'Appointment not found.'}), 404)

        treatment = Treatment.query.filter_by(appointment_id=appointment_id).first()
        if not treatment:
            return make_response(jsonify({'message': 'Treatment not found.'}), 404)

        data = request.get_json() or {}
        diagnosis = data.get('diagnosis')
        prescription = data.get('prescription')
        notes = data.get('notes')

        # Allow doctor or patient to update treatment
        if current_user.has_role('doctor'):
            doctor = DoctorProfile.query.filter_by(user_id=current_user.id).first()
            if not doctor or appt.doctor_id != doctor.id:
                return make_response(jsonify({'message': 'Not authorized to update treatment for this appointment.'}), 403)
        elif current_user.has_role('patient'):
            patient = PatientProfile.query.filter_by(user_id=current_user.id).first()
            if not patient or appt.patient_id != patient.id:
                return make_response(jsonify({'message': 'Not authorized to update treatment for this appointment.'}), 403)
        elif current_user.has_role('admin'):
            pass
        else:
            return make_response(jsonify({'message': 'Not authorized to update treatment.'}), 403)

        if diagnosis is not None:
            treatment.diagnosis = diagnosis
        if prescription is not None:
            treatment.prescription = prescription
        if notes is not None:
            treatment.notes = notes

        db.session.commit()
        return make_response(jsonify({'message': 'Treatment updated.'}), 200)


class DoctorAvailabilityAPI(Resource):
    @auth_token_required
    def get(self, availability_id=None):
        # If id provided, return single availability
        from controllers.models import DoctorAvailability
        if availability_id:
            av = DoctorAvailability.query.get(availability_id)
            if not av:
                return make_response(jsonify({'message': 'Availability not found.'}), 404)
            return make_response(jsonify({'id': av.id, 'doctor_id': av.doctor_id, 'date': av.date.isoformat(), 'start_time': av.start_time.strftime('%H:%M'), 'end_time': av.end_time.strftime('%H:%M')}), 200)

        # optional filter by doctor_id
        doctor_id = request.args.get('doctor_id')
        query = DoctorAvailability.query
        if doctor_id:
            query = query.filter_by(doctor_id=doctor_id)
        avs = query.all()
        resp = []
        for a in avs:
            resp.append({'id': a.id, 'doctor_id': a.doctor_id, 'date': a.date.isoformat(), 'start_time': a.start_time.strftime('%H:%M'), 'end_time': a.end_time.strftime('%H:%M')})
        return make_response(jsonify(resp), 200)

    @auth_token_required
    def post(self):
        # Create availability: admin can provide doctor_id, doctor can create for self
        from controllers.models import DoctorAvailability
        data = request.get_json() or {}
        date_str = data.get('date')
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        doctor_id = data.get('doctor_id')

        if not date_str or not start_time or not end_time:
            return make_response(jsonify({'message': 'date, start_time and end_time are required.'}), 400)

        try:
            date_obj = datetime.fromisoformat(date_str).date()
        except Exception:
            return make_response(jsonify({'message': 'Invalid date format. Use YYYY-MM-DD.'}), 400)

        # Validate date is within same day or next 30 days
        today = date.today()
        max_date = today + timedelta(days=30)
        if date_obj < today:
            return make_response(jsonify({'message': 'Cannot create availability for past dates.'}), 400)
        if date_obj > max_date:
            return make_response(jsonify({'message': 'Cannot create availability beyond 30 days from today.'}), 400)

        try:
            st = datetime.strptime(start_time, '%H:%M').time()
            et = datetime.strptime(end_time, '%H:%M').time()
        except Exception:
            return make_response(jsonify({'message': 'Invalid time format. Use HH:MM.'}), 400)

        # determine doctor_id
        if current_user.has_role('doctor') and not current_user.has_role('admin'):
            doctor = DoctorProfile.query.filter_by(user_id=current_user.id).first()
            if not doctor:
                return make_response(jsonify({'message': 'Doctor profile not found.'}), 404)
            doctor_id = doctor.id
        elif not doctor_id:
            return make_response(jsonify({'message': 'doctor_id is required for non-doctor users.'}), 400)

        av = DoctorAvailability(doctor_id=doctor_id, date=date_obj, start_time=st, end_time=et)
        db.session.add(av)
        db.session.commit()
        return make_response(jsonify({'message': 'Availability created.', 'data': {'id': av.id}}), 201)

    @auth_token_required
    @roles_required('admin')
    def delete(self, availability_id):
        from controllers.models import DoctorAvailability
        av = DoctorAvailability.query.get(availability_id)
        if not av:
            return make_response(jsonify({'message': 'Availability not found.'}), 404)

        # Only admin can delete availability
        db.session.delete(av)
        db.session.commit()
        return make_response(jsonify({'message': 'Availability deleted.'}), 200)


class TreatmentListAPI(Resource):
    @auth_token_required
    def get(self):
        # Return list of treatments joined with their appointments; filter by role
        results = []
        if current_user.has_role('admin'):
            appts = Appointment.query.filter(Appointment.status=='Completed').all()
        elif current_user.has_role('doctor'):
            doctor = DoctorProfile.query.filter_by(user_id=current_user.id).first()
            if not doctor:
                return make_response(jsonify({'message': 'Doctor profile not found for user.'}), 404)
            appts = Appointment.query.filter_by(doctor_id=doctor.id, status='Completed').all()
        else:
            # patient
            patient = PatientProfile.query.filter_by(user_id=current_user.id).first()
            if not patient:
                return make_response(jsonify({'message': 'Patient profile not found for user.'}), 404)
            appts = Appointment.query.filter_by(patient_id=patient.id, status='Completed').all()

        for a in appts:
            treatment = Treatment.query.filter_by(appointment_id=a.id).first()
            if not treatment:
                continue
            doctor = DoctorProfile.query.get(a.doctor_id)
            patient = PatientProfile.query.get(a.patient_id)
            results.append({
                'appointment_id': a.id,
                'date': a.date.isoformat(),
                'time': a.time.strftime('%H:%M'),
                'doctor_id': a.doctor_id,
                'doctor_name': doctor.name if doctor else 'N/A',
                'patient_id': a.patient_id,
                'patient_name': patient.name if patient else 'N/A',
                'diagnosis': treatment.diagnosis,
                'prescription': treatment.prescription,
                'notes': treatment.notes
            })
        return make_response(jsonify(results), 200)




class TreatmentCSVStatusAPI(Resource):
    """
    API endpoint to check status of CSV export task.
    """
    
    @auth_token_required
    def get(self, task_id):
        """
        Check the status of a CSV export task by task ID.
        """
        # Only allow patient to check their own task status
        if not current_user.has_role('patient'):
            return make_response(jsonify({'message': 'Only patients can check export status.'}), 403)
        
        try:
            task_result = celery_app.AsyncResult(task_id)
            
            if task_result.state == 'PENDING':
                return make_response(jsonify({
                    'task_id': task_id,
                    'status': 'pending',
                    'message': 'Task is waiting to be executed'
                }), 200)
            
            elif task_result.state == 'STARTED':
                return make_response(jsonify({
                    'task_id': task_id,
                    'status': 'processing',
                    'message': 'Task is currently processing'
                }), 200)
            
            elif task_result.state == 'SUCCESS':
                result = task_result.result
                if result and isinstance(result, dict) and result.get('status') == 'success':
                    return make_response(jsonify({
                        'task_id': task_id,
                        'status': 'completed',
                        'message': 'CSV export completed successfully',
                        'file_name': result.get('file_name'),
                        'file_path': result.get('file_path')
                    }), 200)
                else:
                    return make_response(jsonify({
                        'task_id': task_id,
                        'status': 'error',
                        'message': (result.get('message') if isinstance(result, dict) else 'Export failed')
                    }), 400)
            
            elif task_result.state == 'FAILURE':
                return make_response(jsonify({
                    'task_id': task_id,
                    'status': 'error',
                    'message': 'Task failed during execution'
                }), 400)
            
            else:
                return make_response(jsonify({
                    'task_id': task_id,
                    'status': task_result.state.lower(),
                    'message': 'Unknown task state'
                }), 200)
        
        except Exception as e:
            # Celery/Redis not available in this environment
            return make_response(jsonify({
                'task_id': task_id,
                'status': 'unavailable',
                'message': 'Async task status unavailable in this environment. If export was run synchronously, check the `exports/` folder in the backend directory.'
            }), 200)


class TreatmentCSVDownloadAPI(Resource):
    """
    API endpoint to download the generated CSV file.
    """
    
    @auth_token_required
    def get(self, filename):
        """
        Download the CSV file by filename.
        """
        # Only patients can download their own files
        if not current_user.has_role('patient'):
            return make_response(jsonify({'message': 'Only patients can download their files.'}), 403)
        
        # Security: Prevent directory traversal attacks
        if '..' in filename or '/' in filename or '\\' in filename:
            return make_response(jsonify({'message': 'Invalid filename.'}), 400)
        
        filepath = os.path.join('exports', filename)
        
        if not os.path.exists(filepath):
            return make_response(jsonify({'message': 'File not found.'}), 404)
        
        try:
            with open(filepath, 'r') as f:
                csv_content = f.read()
            
            response = make_response(csv_content, 200)
            response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            response.headers['Content-Type'] = 'text/csv'
            return response
        
        except Exception as e:
            return make_response(jsonify({'message': f'Error reading file: {str(e)}'}), 500)


class TreatmentCSVExportTriggerAPI(Resource):
    """
    API endpoint to trigger async CSV export of treatment history.
    Patients can request export of their treatment data.
    """
    
    @auth_token_required
    @roles_required('patient')
    def post(self):
        """
        Trigger async CSV export task for current patient.
        Returns task_id for tracking export status.
        """
        try:
            # Get current patient's ID
            patient_id = current_user.id
            
            # Generate unique task ID
            task_id = str(uuid.uuid4())
            
            # Trigger async celery task
            export_treatment_csv.delay(patient_id, task_id)
            
            return make_response(jsonify({
                'status': 'success',
                'message': 'CSV export started. You will receive an email when ready.',
                'task_id': task_id
            }), 202)
        
        except Exception as e:
            return make_response(jsonify({
                'status': 'error',
                'message': f'Failed to start export: {str(e)}'
            }), 500)