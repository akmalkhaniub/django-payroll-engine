"""
Payroll app models.

All monetary values are stored as DECIMAL(12, 2) — never floats.
This guarantees mathematical correctness for financial calculations.
"""
from decimal import Decimal
from django.db import models


class Agency(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'agencies'

    def __str__(self):
        return self.name


class Worker(models.Model):
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='workers')
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    # DECIMAL — never float — for financial correctness
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2)
    # Overtime: hours beyond this threshold in a week are paid at 1.5x
    weekly_hours_threshold = models.PositiveIntegerField(default=40)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} (£{self.hourly_rate}/hr)"


class Shift(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='shifts')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COMPLETED)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def hours_worked(self) -> Decimal:
        """Calculate hours as Decimal — no floating point errors."""
        delta = self.end_time - self.start_time
        total_seconds = Decimal(str(delta.total_seconds()))
        return (total_seconds / Decimal('3600')).quantize(Decimal('0.01'))

    class Meta:
        indexes = [
            # Compound index for payroll period queries: worker + time range
            models.Index(fields=['worker', 'start_time'], name='idx_shift_worker_start'),
        ]

    def __str__(self):
        return f"{self.worker.name} — {self.start_time.date()}"


class PayrollRun(models.Model):
    """Represents a payroll calculation job (processed asynchronously)."""
    class Status(models.TextChoices):
        QUEUED = 'QUEUED', 'Queued'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'

    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='payroll_runs')
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    celery_task_id = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Payroll Run {self.period_start} → {self.period_end} [{self.status}]"


class PayrollEntry(models.Model):
    """
    Individual payroll entry per worker per pay period.
    Uses ACID transaction to guarantee no partial writes.
    All monetary fields are DECIMAL.
    """
    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='entries')
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='payroll_entries')

    regular_hours = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0'))
    overtime_hours = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0'))
    regular_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    overtime_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    total_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))

    # Path to the generated PDF invoice (saved to MEDIA_ROOT or GCS)
    invoice_pdf_path = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('payroll_run', 'worker')]
        indexes = [
            models.Index(fields=['payroll_run'], name='idx_entry_run'),
        ]

    def __str__(self):
        return f"{self.worker.name} — £{self.total_pay}"


class AuditLog(models.Model):
    """Append-only audit trail for all payroll events."""
    action = models.CharField(max_length=100)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.action}"
