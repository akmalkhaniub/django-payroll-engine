"""Expose Celery app so Django's manage.py picks it up."""
from .celery import app as celery_app

__all__ = ('celery_app',)
