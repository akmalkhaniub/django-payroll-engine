"""Payroll app URL routing."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AgencyViewSet, WorkerViewSet, ShiftViewSet,
    PayrollRunViewSet, PayrollEntryViewSet,
)

router = DefaultRouter()
router.register('agencies', AgencyViewSet)
router.register('workers', WorkerViewSet)
router.register('shifts', ShiftViewSet)
router.register('payroll-runs', PayrollRunViewSet)
router.register('payroll-entries', PayrollEntryViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
