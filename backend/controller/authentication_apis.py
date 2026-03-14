from flask_restful import Resource
from flask import request, jsonify, make_response
from flask_security import utils, auth_token_required, roles_required, hash_password

from controllers.user_datastore import user_datastore
from controllers.database import db
from controllers.models import PatientProfile

"""Authentication API resources: login, logout, register, and email check.

This module provides Resource classes used by the API. Register creates a user,
assigns the patient role, and creates a PatientProfile record. Other resources
handle login, logout, and email availability checks.
"""

class CheckEmailAPI(Resource):
    def post(self):
        crediential = request.get_json()

        if not crediential:
            result = {
                'message': 'Request body is required.'
            }
            return make_response(jsonify(result), 400)
        
        email = crediential.get('email', None)

        if not email:
            result = {
                'message': 'Email is required.'
            }
            return make_response(jsonify(result), 400)
        
        user = user_datastore.find_user(email=email)
        if user:
            return make_response(jsonify({'available': False}), 200)
        else:
            return make_response(jsonify({'available': True}), 200)


class LoginAPI(Resource):
    def post(self):

        login_credentials = request.get_json()

        #data validation
        if not login_credentials:
            result = {
                'message': 'Login credentials are required.'
            }
            return make_response(jsonify(result), 400)
        
        email = login_credentials.get('email', None)
        password = login_credentials.get('password',None)
        
        if not email or not password:
            result = {
                'message': 'Email and password are required.'
            }
            return make_response(jsonify(result), 400)
        
        user = user_datastore.find_user(email=email)

        if not user:
            result = {
                'message': 'User not found.'
            }
            return make_response(jsonify(result), 404)
        
        
        if not utils.verify_password(password, user.password):
            result = {
                'message': 'Invalid password.'
            }
            return make_response(jsonify(result), 401)
        
        # Check if user is blocked (active=False)
        if not user.active:
            result = {
                'message': 'Your account has been blocked. Please contact an administrator.'
            }
            return make_response(jsonify(result), 403)
        
        auth_token = user.get_auth_token()

        utils.login_user(user)

        response = {
            'message': 'Login successful.',
            'user_details' : {
                'email': user.email,
                'roles': [role.name for role in user.roles],
                'auth_token': auth_token
            }
        }

        return make_response(jsonify(response), 200)

class LogoutAPI(Resource):
    @auth_token_required
    # @roles_required(['admin'])
    def post(self):
        utils.logout_user()
        response = {
            'message': 'Logout successful.'
        }
        return make_response(jsonify(response), 200)
    

class RegisterAPI(Resource):
    def post(self):
        creds = request.get_json()

        if not creds:
            result = {
                'message': 'Registration credentials are required.'
            }
            return make_response(jsonify(result), 400)
        
        email = creds.get('email', None)
        password = creds.get('password', None)

        if not email or not password:
            result = {
                'message': 'Email and password are required.'
            }
            return make_response(jsonify(result), 400)
        
        if user_datastore.find_user(email=email):
            result = {
                'message': 'User already exists.'
            }
            return make_response(jsonify(result), 409)

        # ensure patient role exists and assign
        patient_role = user_datastore.find_or_create_role(name='patient', description='Patient')

        # create user with hashed password
        patient_user = user_datastore.create_user(
            email=email,
            roles=[patient_role]
        )
        patient_user.password = hash_password(password)
        db.session.add(patient_user)
        db.session.commit()

        # create patient profile for the new user
        user = user_datastore.find_user(email=email)
        name = creds.get('name') or email
        age = creds.get('age')
        gender = creds.get('gender')
        contact = creds.get('contact')
        address = creds.get('address')

        patient = PatientProfile(user_id=user.id, name=name, age=age, gender=gender, contact=contact, address=address)
        db.session.add(patient)
        db.session.commit()

        response = {
            'message': 'Registration successful.',
            'user_details': {
                'email': email,
                'roles': [patient_role.name]
            }
        }
        return make_response(jsonify(response), 201)



    # def get(self):
    #     pass

    # def put(self):
    #     pass