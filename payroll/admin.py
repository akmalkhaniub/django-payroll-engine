"""Payroll app admin configuration."""
from django.contrib import admin
from .models import Agency, Worker, Shift, PayrollRun, PayrollEntry, AuditLog


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at']


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'hourly_rate', 'weekly_hours_threshold', 'agency']
    list_filter = ['agency']
    search_fields = ['name', 'email']


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ['worker', 'start_time', 'end_time', 'status']
    list_filter = ['status', 'worker__agency']
    ordering = ['-start_time']


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ['agency', 'period_start', 'period_end', 'status', 'created_at']
    list_filter = ['status', 'agency']
    readonly_fields = ['celery_task_id', 'error_message', 'completed_at']


@admin.register(PayrollEntry)
class PayrollEntryAdmin(admin.ModelAdmin):
    list_display = ['worker', 'payroll_run', 'regular_hours', 'overtime_hours', 'total_pay']
    list_filter = ['payroll_run__agency']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'created_at']
    readonly_fields = ['action', 'payload', 'created_at']
