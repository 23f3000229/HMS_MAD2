"""
Celery task definitions for the hospital management system.
Includes:
- Daily reminder notifications for same-day appointments
- Monthly report generation for doctors
- User-triggered CSV export of treatment history
"""

from celery_config import celery_app, init_celery
from controllers.database import db
from controllers.models import User, Appointment, DoctorProfile, PatientProfile, Treatment
from datetime import datetime, date, timedelta
from flask import Flask
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import os
import json

# Email configuration (will use mailhog in development)
MAIL_SERVER = os.environ.get('MAIL_SERVER', 'localhost')
MAIL_PORT = int(os.environ.get('MAIL_PORT', 1025))
MAIL_USERNAME = os.environ.get('MAIL_USERNAME', 'noreply@hospital.com')
MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', False)


def send_email(subject, recipients, body, html_body=None):
    """
    Send email using SMTP (configured for mailhog in dev).
    
    Args:
        subject: Email subject
        recipients: List of email addresses
        body: Plain text body
        html_body: Optional HTML body
    """
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = MAIL_USERNAME
        msg['To'] = ','.join(recipients)
        
        # Attach plain text version
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach HTML version if provided
        if html_body:
            msg.attach(MIMEText(html_body, 'html'))
        
        # Connect to SMTP server (mailhog)
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            if MAIL_USE_TLS:
                server.starttls()
            server.send_message(msg)
        
        print(f"✓ Email sent to {recipients}")
        return True
    except Exception as e:
        print(f"✗ Failed to send email: {str(e)}")
        return False


@celery_app.task(bind=True, name='celery_tasks.send_daily_reminders')
def send_daily_reminders(self):
    """
    Send reminder notifications to patients with appointments today.
    Scheduled to run daily at 8:00 AM.
    """
    try:
        print("📧 Starting daily reminder job...")
        
        # Get appointments for today
        today = date.today()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        appointments = Appointment.query.filter(
            Appointment.date == today,
            Appointment.status == 'Booked'
        ).all()
        
        if not appointments:
            print("✓ No appointments today")
            return {'status': 'success', 'message': 'No appointments today', 'count': 0}
        
        reminder_count = 0
        
        for appt in appointments:
            # Get patient and doctor info
            patient = PatientProfile.query.get(appt.patient_id)
            doctor = DoctorProfile.query.get(appt.doctor_id)
            
            if not patient:
                continue
            
            # Get patient user email
            user = User.query.get(patient.user_id)
            if not user or not user.email:
                continue
            
            # Prepare reminder message
            subject = f"Reminder: Appointment with {doctor.name if doctor else 'Doctor'} Today"
            body = f"""
Dear {patient.name},

This is a reminder that you have an appointment today:

Doctor: {doctor.name if doctor else 'N/A'}
Time: {appt.time.strftime('%H:%M')}

Please arrive 10 minutes before your scheduled time.

Best regards,
Hospital Management System
"""
            
            html_body = f"""
<html>
    <body>
        <h2>Appointment Reminder</h2>
        <p>Dear {patient.name},</p>
        <p>This is a reminder that you have an appointment <strong>today</strong>:</p>
        <ul>
            <li><strong>Doctor:</strong> {doctor.name if doctor else 'N/A'}</li>
            <li><strong>Time:</strong> {appt.time.strftime('%H:%M')}</li>
        </ul>
        <p>Please arrive 10 minutes before your scheduled time.</p>
        <hr>
        <p><em>Hospital Management System</em></p>
    </body>
</html>
"""
            
            # Send email
            if send_email(subject, [user.email], body, html_body):
                reminder_count += 1
        
        print(f"✓ Daily reminder job completed - {reminder_count} reminders sent")
        return {
            'status': 'success',
            'message': f'Reminders sent for {reminder_count} appointments',
            'count': reminder_count
        }
    
    except Exception as e:
        print(f"✗ Daily reminder job failed: {str(e)}")
        raise


@celery_app.task(bind=True, name='celery_tasks.generate_monthly_reports')
def generate_monthly_reports(self):
    """
    Generate monthly reports for each doctor with their appointments and treatments.
    Reports include: Appointments count, Treatments given, Diagnosis summary.
    Scheduled to run on 1st of each month at 9:00 AM.
    """
    try:
        print("📊 Starting monthly report generation job...")
        
        # Get all active doctors
        doctors = DoctorProfile.query.filter(
            ~DoctorProfile.name.ilike('[ARCHIVED]%')
        ).all()
        
        if not doctors:
            print("✓ No active doctors found")
            return {'status': 'success', 'message': 'No active doctors', 'count': 0}
        
        # Get previous month
        today = date.today()
        first_day_this_month = today.replace(day=1)
        last_day_prev_month = first_day_this_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)
        
        report_count = 0
        
        for doctor in doctors:
            # Get doctor user email
            user = User.query.get(doctor.user_id)
            if not user or not user.email:
                continue
            
            # Get appointments for previous month
            appointments = Appointment.query.filter(
                Appointment.doctor_id == doctor.id,
                Appointment.date >= first_day_prev_month,
                Appointment.date <= last_day_prev_month,
                Appointment.status == 'Completed'
            ).all()
            
            if not appointments:
                continue
            
            # Count statistics
            total_appointments = len(appointments)
            treatments_given = Treatment.query.join(Appointment).filter(
                Appointment.doctor_id == doctor.id,
                Appointment.date >= first_day_prev_month,
                Appointment.date <= last_day_prev_month,
                Appointment.status == 'Completed'
            ).count()
            
            # Prepare report message
            subject = f"Monthly Report - {last_day_prev_month.strftime('%B %Y')}"
            body = f"""
Dear Dr. {doctor.name},

Here is your monthly activity report for {last_day_prev_month.strftime('%B %Y')}:

Statistics:
- Total Appointments: {total_appointments}
- Treatments Given: {treatments_given}

Thank you for your service.

Best regards,
Hospital Management System
"""
            
            html_body = f"""
<html>
    <body>
        <h2>Monthly Activity Report</h2>
        <p>Dear Dr. {doctor.name},</p>
        <p>Here is your monthly activity report for <strong>{last_day_prev_month.strftime('%B %Y')}</strong>:</p>
        <table border="1" cellpadding="10">
            <tr>
                <th>Metric</th>
                <th>Count</th>
            </tr>
            <tr>
                <td>Total Appointments</td>
                <td>{total_appointments}</td>
            </tr>
            <tr>
                <td>Treatments Given</td>
                <td>{treatments_given}</td>
            </tr>
        </table>
        <p><br/>Thank you for your service.</p>
        <hr>
        <p><em>Hospital Management System</em></p>
    </body>
</html>
"""
            
            # Send email
            if send_email(subject, [user.email], body, html_body):
                report_count += 1
        
        print(f"✓ Monthly report job completed - {report_count} reports generated")
        return {
            'status': 'success',
            'message': f'Monthly reports generated for {report_count} doctors',
            'count': report_count
        }
    
    except Exception as e:
        print(f"✗ Monthly report job failed: {str(e)}")
        raise


@celery_app.task(bind=True, name='celery_tasks.export_treatment_csv')
def export_treatment_csv(self, patient_id, task_id):
    """
    Export patient's treatment history to CSV asynchronously.
    User-triggered task that notifies patient when complete.
    
    Args:
        patient_id: ID of patient requesting export
        task_id: Unique task ID for tracking
    """
    try:
        print(f"📥 Starting CSV export for patient {patient_id}...")
        
        patient = PatientProfile.query.get(patient_id)
        if not patient:
            return {'status': 'error', 'message': 'Patient not found'}
        
        # Get all completed appointments with treatments
        appointments = Appointment.query.filter(
            Appointment.patient_id == patient_id,
            Appointment.status == 'Completed'
        ).all()
        
        # Build CSV data
        csv_headers = ['Date', 'Time', 'Doctor', 'Diagnosis', 'Prescription', 'Notes']
        csv_rows = []
        
        for appt in appointments:
            treatment = Treatment.query.filter_by(appointment_id=appt.id).first()
            doctor = DoctorProfile.query.get(appt.doctor_id)
            
            if treatment:
                csv_rows.append([
                    appt.date.isoformat(),
                    appt.time.strftime('%H:%M'),
                    doctor.name if doctor else 'N/A',
                    treatment.diagnosis or '',
                    treatment.prescription or '',
                    treatment.notes or ''
                ])
        
        # Create exports directory if it doesn't exist
        os.makedirs('exports', exist_ok=True)
        
        # Write CSV file
        filename = f"treatments_{patient_id}_{task_id}.csv"
        filepath = os.path.join('exports', filename)
        
        with open(filepath, 'w') as f:
            # Write headers
            f.write(','.join(csv_headers) + '\n')
            # Write rows
            for row in csv_rows:
                f.write(','.join(str(cell) for cell in row) + '\n')
        
        # Send completion notification email
        user = User.query.get(patient.user_id)
        if user and user.email:
            subject = "Your Treatment History Export is Ready"
            body = f"""
Dear {patient.name},

Your treatment history export is ready for download.

Filename: {filename}

You can access it through your dashboard.

Best regards,
Hospital Management System
"""
            send_email(subject, [user.email], body)
        
        print(f"✓ CSV export completed - {filename}")
        return {
            'status': 'success',
            'message': 'Export completed',
            'filename': filename,
            'file_path': filepath
        }
    
    except Exception as e:
        print(f"✗ CSV export failed: {str(e)}")
        return {'status': 'error', 'message': str(e)}
