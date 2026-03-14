from flask import Flask
from flask_security import Security, hash_password
from flask_restful import Api
from flask_cors import CORS

from controllers.database import db
from controllers.config import Config
from controllers.user_datastore import user_datastore
from celery_config import init_celery

"""Application factory and API registration for the hospital backend.

This module sets up Flask, SQLAlchemy, Flask-Security, CORS, Celery, and registers
API resources under the `/api` prefix.
"""


def create_app():

    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    security = Security(app, user_datastore)

    api = Api(app, prefix='/api')

    @app.route("/")
    def index():
        return {"message": "Hospital backend running"}, 200


    with app.app_context():
        db.create_all()

        # ensure roles
        admin_role = user_datastore.find_or_create_role(name='admin', description='Administrator')
        doctor_role = user_datastore.find_or_create_role(name='doctor', description='Doctor')
        patient_role = user_datastore.find_or_create_role(name='patient', description='Patient')

        # default admin user
        if not user_datastore.find_user(email='admin@hospital.com'):
            admin_user = user_datastore.create_user(
                email='admin@hospital.com',
                roles=[admin_role]
            )
            # Hash and set the password
            admin_user.password = hash_password('admin123')
            db.session.add(admin_user)
            db.session.commit()

        db.session.commit()

    return app, api


app, api = create_app()

# Initialize Celery with Flask app context
celery = init_celery(app)

# Allow local frontend dev servers
CORS(app, origins=[
        "http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174",
    ])

# api.add_resource(Index, '/')

from controllers.authentication_apis import LoginAPI, LogoutAPI, RegisterAPI, CheckEmailAPI
api.add_resource(LoginAPI, '/login')
api.add_resource(LogoutAPI, '/logout')
api.add_resource(RegisterAPI, '/register')
api.add_resource(CheckEmailAPI, '/check-email')

from controllers.crud_apis import DepartmentCrudAPI, DoctorCrudAPI, AppointmentAPI, TreatmentAPI, TreatmentListAPI, BookedSlotsAPI, TreatmentCSVExportTriggerAPI, TreatmentCSVStatusAPI, TreatmentCSVDownloadAPI
api.add_resource(DepartmentCrudAPI, '/departments', '/departments/<int:department_id>')
api.add_resource(DoctorCrudAPI, '/doctors', '/doctors/<int:doctor_id>')
from controllers.crud_apis import DoctorMeAPI, PatientCrudAPI, PatientMeAPI
api.add_resource(DoctorMeAPI, '/doctors/me')
api.add_resource(PatientMeAPI, '/patients/me')
api.add_resource(PatientCrudAPI, '/patients', '/patients/<int:patient_id>')
api.add_resource(AppointmentAPI, '/appointments', '/appointments/<int:appointment_id>')
api.add_resource(BookedSlotsAPI, '/booked-slots')
api.add_resource(TreatmentAPI, '/appointments/<int:appointment_id>/treatment')
api.add_resource(TreatmentListAPI, '/treatments')
from controllers.crud_apis import DoctorAvailabilityAPI
api.add_resource(DoctorAvailabilityAPI, '/availabilities', '/availabilities/<int:availability_id>')

# Treatment CSV export endpoints
api.add_resource(TreatmentCSVExportTriggerAPI, '/export-treatment-csv')
api.add_resource(TreatmentCSVStatusAPI, '/export-treatment-csv/status/<string:task_id>')
api.add_resource(TreatmentCSVDownloadAPI, '/export-treatment-csv/download/<string:filename>')

if __name__ == "__main__":
    app.run(debug=True)
