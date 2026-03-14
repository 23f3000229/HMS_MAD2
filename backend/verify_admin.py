#!/usr/bin/env python
"""Test to verify admin password is hashed in the database."""

from flask import Flask
from flask_security import Security
from controllers.config import Config
from controllers.database import db
from controllers.user_datastore import user_datastore
from controllers.models import User

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
security = Security(app, user_datastore)

with app.app_context():
    db.create_all()
    
    # Check if admin exists
    admin = User.query.filter_by(email='admin@hospital.com').first()
    if admin:
        print(f"✓ Admin user found: {admin.email}")
        print(f"✓ Password hash: {admin.password[:50]}...")
        print(f"✓ Password hash length: {len(admin.password)}")
        
        # Check if it looks like an argon2 hash
        if admin.password.startswith('$argon2'):
            print("✓ Password is properly hashed with argon2!")
        else:
            print("⚠ Password may not be hashed properly")
    else:
        print("✓ Creating admin user with hashed password...")
        from flask_security import utils
        admin_role = user_datastore.find_or_create_role(name='admin', description='Administrator')
        hashed = utils.hash_password('admin123')
        user_datastore.create_user(
            email='admin@hospital.com',
            password=hashed,
            roles=[admin_role]
        )
        db.session.commit()
        print("✓ Admin user created with hashed password!")
        
        admin = User.query.filter_by(email='admin@hospital.com').first()
        print(f"✓ Password: {admin.password[:50]}...")
