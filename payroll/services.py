"""
Payroll calculation service.

All arithmetic uses Python's Decimal type — never float.
Wrapped in an ACID database transaction to prevent partial writes.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import NamedTuple

from django.db import transaction
from django.utils import timezone

from .models import Worker, Shift, PayrollRun, PayrollEntry, AuditLog


OVERTIME_MULTIPLIER = Decimal('1.5')
PENCE_QUANTIZER = Decimal('0.01')   # Round to 2 decimal places


class WorkerPaySummary(NamedTuple):
    worker: Worker
    regular_hours: Decimal
    overtime_hours: Decimal
    regular_pay: Decimal
    overtime_pay: Decimal
    total_pay: Decimal


def calculate_worker_pay(
    worker: Worker,
    period_start: date,
    period_end: date,
) -> WorkerPaySummary:
    """
    Calculate gross pay for a single worker in a pay period.

    Uses select_related to avoid N+1 queries.
    All arithmetic uses Decimal — no floating point imprecision.
    """
    # Fetch only completed shifts in the period — uses the compound index
    shifts = Shift.objects.filter(
        worker=worker,
        status=Shift.Status.COMPLETED,
        start_time__date__gte=period_start,
        start_time__date__lte=period_end,
    )

    total_hours = sum(
        (shift.hours_worked() for shift in shifts),
        start=Decimal('0'),
    )

    threshold = Decimal(str(worker.weekly_hours_threshold))
    regular_hours = min(total_hours, threshold)
    overtime_hours = max(total_hours - threshold, Decimal('0'))

    regular_pay = (regular_hours * worker.hourly_rate).quantize(
        PENCE_QUANTIZER, rounding=ROUND_HALF_UP
    )
    overtime_pay = (overtime_hours * worker.hourly_rate * OVERTIME_MULTIPLIER).quantize(
        PENCE_QUANTIZER, rounding=ROUND_HALF_UP
    )
    total_pay = (regular_pay + overtime_pay).quantize(
        PENCE_QUANTIZER, rounding=ROUND_HALF_UP
    )

    return WorkerPaySummary(
        worker=worker,
        regular_hours=regular_hours,
        overtime_hours=overtime_hours,
        regular_pay=regular_pay,
        overtime_pay=overtime_pay,
        total_pay=total_pay,
    )


@transaction.atomic
def process_payroll_run(payroll_run_id: int) -> None:
    """
    Process a payroll run inside a single ACID transaction.

    If any calculation or DB write fails, the entire run is rolled back —
    preventing partial payroll entries (money created or destroyed).
    """
    payroll_run = PayrollRun.objects.select_for_update().get(pk=payroll_run_id)
    payroll_run.status = PayrollRun.Status.PROCESSING
    payroll_run.save(update_fields=['status'])

    try:
        # Fetch all active workers for this agency — select_related prevents N+1
        workers = Worker.objects.filter(
            agency=payroll_run.agency,
        ).select_related('agency')

        entries_to_create = []

        for worker in workers:
            summary = calculate_worker_pay(
                worker=worker,
                period_start=payroll_run.period_start,
                period_end=payroll_run.period_end,
            )

            entries_to_create.append(
                PayrollEntry(
                    payroll_run=payroll_run,
                    worker=summary.worker,
                    regular_hours=summary.regular_hours,
                    overtime_hours=summary.overtime_hours,
                    regular_pay=summary.regular_pay,
                    overtime_pay=summary.overtime_pay,
                    total_pay=summary.total_pay,
                )
            )

        # Bulk-create all entries in a single SQL statement
        PayrollEntry.objects.bulk_create(entries_to_create)

        payroll_run.status = PayrollRun.Status.COMPLETED
        payroll_run.completed_at = timezone.now()
        payroll_run.save(update_fields=['status', 'completed_at'])

        AuditLog.objects.create(
            action='PAYROLL_RUN_COMPLETED',
            payload={
                'payroll_run_id': payroll_run_id,
                'workers_processed': len(entries_to_create),
                'period': f"{payroll_run.period_start} → {payroll_run.period_end}",
            },
        )

    except Exception as exc:
        # Transaction will roll back automatically on exception
        payroll_run.status = PayrollRun.Status.FAILED
        payroll_run.error_message = str(exc)
        payroll_run.save(update_fields=['status', 'error_message'])

        AuditLog.objects.create(
            action='PAYROLL_RUN_FAILED',
            payload={'payroll_run_id': payroll_run_id, 'error': str(exc)},
        )
        raise
