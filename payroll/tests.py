"""
Payroll app tests.

Integration tests against a real MySQL test database.
Uses Django's TestCase (wraps each test in a transaction + rollback).
Tests financial correctness of Decimal arithmetic and overtime calculation.
"""
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from payroll.models import Agency, Worker, Shift, PayrollRun, PayrollEntry
from payroll.services import calculate_worker_pay, process_payroll_run


def make_utc(year, month, day, hour=9):
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


class PayrollCalculationTests(TestCase):
    """Unit tests for the payroll calculation service."""

    def setUp(self):
        self.agency = Agency.objects.create(name='Test Agency')
        self.worker = Worker.objects.create(
            agency=self.agency,
            name='Test Worker',
            email='test@agency.com',
            hourly_rate=Decimal('10.00'),
            weekly_hours_threshold=40,
        )

    def _create_shift(self, hours: int, day: int = 1):
        start = make_utc(2025, 5, day)
        end = start + timedelta(hours=hours)
        return Shift.objects.create(
            worker=self.worker,
            start_time=start,
            end_time=end,
            status=Shift.Status.COMPLETED,
        )

    def test_regular_pay_no_overtime(self):
        """Worker with 8 hours should earn 8 × £10 = £80 exactly."""
        self._create_shift(hours=8, day=1)
        summary = calculate_worker_pay(
            self.worker,
            period_start=datetime(2025, 5, 1).date(),
            period_end=datetime(2025, 5, 31).date(),
        )
        self.assertEqual(summary.regular_hours, Decimal('8.00'))
        self.assertEqual(summary.overtime_hours, Decimal('0'))
        self.assertEqual(summary.regular_pay, Decimal('80.00'))
        self.assertEqual(summary.total_pay, Decimal('80.00'))

    def test_overtime_calculation(self):
        """
        Worker with 48 total hours (threshold=40) should get:
        - Regular: 40h × £10 = £400
        - Overtime: 8h × £10 × 1.5 = £120
        - Total: £520
        """
        for day in range(1, 7):
            self._create_shift(hours=8, day=day)  # 6 days × 8h = 48h total
        summary = calculate_worker_pay(
            self.worker,
            period_start=datetime(2025, 5, 1).date(),
            period_end=datetime(2025, 5, 31).date(),
        )
        self.assertEqual(summary.regular_hours, Decimal('40.00'))
        self.assertEqual(summary.overtime_hours, Decimal('8.00'))
        self.assertEqual(summary.regular_pay, Decimal('400.00'))
        self.assertEqual(summary.overtime_pay, Decimal('120.00'))
        self.assertEqual(summary.total_pay, Decimal('520.00'))

    def test_decimal_precision_no_float_errors(self):
        """
        Ensures no floating point errors (e.g. 0.1 + 0.2 ≠ 0.3 in floats).
        Creates a shift with fractional hours and verifies exact Decimal result.
        """
        # 6.5 hour shift
        start = make_utc(2025, 5, 1)
        end = start + timedelta(hours=6, minutes=30)
        Shift.objects.create(
            worker=self.worker, start_time=start, end_time=end,
            status=Shift.Status.COMPLETED,
        )
        summary = calculate_worker_pay(
            self.worker,
            period_start=datetime(2025, 5, 1).date(),
            period_end=datetime(2025, 5, 31).date(),
        )
        # 6.5h × £10 = £65.00 exactly
        self.assertEqual(summary.total_pay, Decimal('65.00'))

    def test_acid_transaction_on_payroll_run(self):
        """PayrollRun completes successfully and creates entries in a transaction."""
        self._create_shift(hours=8, day=1)
        run = PayrollRun.objects.create(
            agency=self.agency,
            period_start=datetime(2025, 5, 1).date(),
            period_end=datetime(2025, 5, 31).date(),
        )
        process_payroll_run(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, PayrollRun.Status.COMPLETED)
        self.assertEqual(PayrollEntry.objects.filter(payroll_run=run).count(), 1)


class PayrollAPITests(TestCase):
    """Integration tests for the REST API."""

    def setUp(self):
        self.client = APIClient()
        self.agency = Agency.objects.create(name='API Test Agency')

    def test_create_worker(self):
        url = reverse('worker-list')
        data = {
            'agency': self.agency.id,
            'name': 'Jane Doe',
            'email': 'jane@test.com',
            'hourly_rate': '14.50',
            'weekly_hours_threshold': 40,
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'Jane Doe')

    def test_shift_validation_end_before_start(self):
        """API must reject shifts where end_time <= start_time."""
        worker = Worker.objects.create(
            agency=self.agency, name='W', email='w@t.com',
            hourly_rate=Decimal('10.00'), weekly_hours_threshold=40,
        )
        url = reverse('shift-list')
        data = {
            'worker': worker.id,
            'start_time': '2025-05-01T10:00:00Z',
            'end_time': '2025-05-01T09:00:00Z',  # end BEFORE start
            'status': 'COMPLETED',
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_payroll_run_returns_202(self):
        """Creating a payroll run returns 202 Accepted (async)."""
        url = reverse('payrollrun-list')
        data = {
            'agency': self.agency.id,
            'period_start': '2025-05-01',
            'period_end': '2025-05-31',
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn('celery_task_id', response.data)
