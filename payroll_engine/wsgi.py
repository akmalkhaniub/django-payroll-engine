"""WSGI config for payroll_engine project."""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'payroll_engine.settings')
application = get_wsgi_application()
