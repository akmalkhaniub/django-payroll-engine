"""Celery application entry point."""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'payroll_engine.settings')

app = Celery('payroll_engine')
app.config_from_object('django.conf:settings', namespace='CELERY')

# Autodiscover tasks from all installed apps
app.autodiscover_tasks()
