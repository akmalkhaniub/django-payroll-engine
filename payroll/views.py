"""DRF API views for the payroll app."""
from django.http import FileResponse
from django.conf import settings
import os

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Agency, Worker, Shift, PayrollRun, PayrollEntry
from .serializers import (
    AgencySerializer, WorkerSerializer, ShiftSerializer,
    PayrollRunSerializer, PayrollRunCreateSerializer, PayrollEntrySerializer,
)
from .tasks import run_payroll_task, dispatch_invoice_generation


class AgencyViewSet(viewsets.ModelViewSet):
    queryset = Agency.objects.all()
    serializer_class = AgencySerializer


class WorkerViewSet(viewsets.ModelViewSet):
    queryset = Worker.objects.select_related('agency').all()
    serializer_class = WorkerSerializer
    filterset_fields = ['agency']


class ShiftViewSet(viewsets.ModelViewSet):
    """
    CRUD for shifts.
    Uses select_related to prevent N+1 queries on list responses.
    """
    queryset = Shift.objects.select_related('worker', 'worker__agency').all()
    serializer_class = ShiftSerializer
    filterset_fields = ['worker', 'status']
    ordering_fields = ['start_time', 'created_at']


class PayrollRunViewSet(viewsets.ModelViewSet):
    """
    Create a payroll run → instantly queued as a background Celery task.
    The HTTP response returns immediately with status=QUEUED + celery task ID.
    """
    queryset = PayrollRun.objects.prefetch_related(
        'entries', 'entries__worker'
    ).select_related('agency').all()
    filterset_fields = ['agency', 'status']

    def get_serializer_class(self):
        if self.action == 'create':
            return PayrollRunCreateSerializer
        return PayrollRunSerializer

    def create(self, request, *args, **kwargs):
        serializer = PayrollRunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payroll_run = serializer.save()

        # Dispatch the heavy computation to a Celery worker — non-blocking
        task = run_payroll_task.delay(payroll_run.id)

        # Store Celery task ID so clients can poll status
        payroll_run.celery_task_id = task.id
        payroll_run.save(update_fields=['celery_task_id'])

        return Response(
            {
                'id': payroll_run.id,
                'status': payroll_run.status,
                'celery_task_id': task.id,
                'message': 'Payroll run queued. Poll /api/payroll-runs/{id}/ for status.',
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'], url_path='generate-invoices')
    def generate_invoices(self, request, pk=None):
        """Fan out PDF generation tasks for all entries in this run."""
        payroll_run = self.get_object()
        if payroll_run.status != PayrollRun.Status.COMPLETED:
            return Response(
                {'error': 'Payroll run is not completed yet.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        dispatch_invoice_generation.delay(payroll_run.id)
        return Response({'message': 'Invoice generation queued for all workers.'})


class PayrollEntryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PayrollEntry.objects.select_related(
        'worker', 'payroll_run'
    ).all()
    serializer_class = PayrollEntrySerializer
    filterset_fields = ['payroll_run', 'worker']

    @action(detail=True, methods=['get'], url_path='invoice')
    def download_invoice(self, request, pk=None):
        """Stream the PDF invoice directly from disk (or GCS in production)."""
        entry = self.get_object()
        if not entry.invoice_pdf_path:
            return Response(
                {'error': 'Invoice not yet generated. POST to /generate-invoices/ first.'},
                status=status.HTTP_404_NOT_FOUND
            )
        filepath = os.path.join(settings.MEDIA_ROOT, entry.invoice_pdf_path)
        if not os.path.exists(filepath):
            return Response({'error': 'Invoice file not found.'}, status=status.HTTP_404_NOT_FOUND)
        return FileResponse(open(filepath, 'rb'), content_type='application/pdf')
