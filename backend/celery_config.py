"""
Celery configuration and task definitions for the hospital management system.
Handles background jobs like daily reminders, monthly reports, and CSV exports.
"""

from celery import Celery
from flask import Flask
from kombu import Queue, Exchange
import os

# Initialize Celery
celery_app = Celery(__name__)

# Celery configuration
class CeleryConfig:
    # Redis as message broker
    broker_url = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    result_backend = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
    
    # Task settings
    task_serializer = 'json'
    accept_content = ['json']
    result_serializer = 'json'
    timezone = 'UTC'
    enable_utc = True
    
    # Task routing
    task_routes = {
        'celery_tasks.send_daily_reminder*': {'queue': 'default'},
        'celery_tasks.generate_monthly_report*': {'queue': 'default'},
        'celery_tasks.export_treatment_csv*': {'queue': 'csv_export'},
    }
    
    # Queue definitions
    task_queues = (
        Queue('default', Exchange('default'), routing_key='default'),
        Queue('csv_export', Exchange('csv_export'), routing_key='csv_export'),
    )
    
    # Task execution settings
    task_track_started = True
    task_time_limit = 30 * 60  # 30 minutes abort timeout
    task_soft_time_limit = 25 * 60  # 25 minutes soft timeout for email/etc
    task_acks_late = True
    worker_prefetch_multiplier = 1
    
    # Retry settings
    task_autoretry_for = (Exception,)
    task_max_retries = 3
    task_default_retry_delay = 60


def init_celery(app: Flask) -> Celery:
    """
    Initialize Celery with Flask app context.
    Allows tasks to access Flask app context when needed.
    """
    celery_app.config_from_object(CeleryConfig)
    
    class ContextTask(celery_app.Task):
        """Make celery tasks work with Flask app context."""
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    
    celery_app.Task = ContextTask
    return celery_app


# Scheduled tasks (using Celery Beat)
from celery.schedules import crontab

class CeleryBeatConfig:
    """
    Celery Beat schedule configuration for periodic tasks.
    """
    schedule = {
        'send-daily-reminders': {
            'task': 'celery_tasks.send_daily_reminders',
            'schedule': crontab(hour=8, minute=0),  # Every day at 8:00 AM
            'options': {'queue': 'default'}
        },
        'generate-monthly-reports': {
            'task': 'celery_tasks.generate_monthly_reports',
            'schedule': crontab(day_of_month=1, hour=9, minute=0),  # 1st of each month at 9:00 AM
            'options': {'queue': 'default'}
        }
    }
