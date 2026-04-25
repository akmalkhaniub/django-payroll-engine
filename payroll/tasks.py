"""
Celery tasks for asynchronous payroll processing.

PDF generation is a CPU-bound operation that would block the Python GIL
if done synchronously in the Django view. By offloading to Celery workers,
HTTP responses return immediately and the system remains non-blocking.
"""
import io
import os
from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import PayrollRun, PayrollEntry, AuditLog


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_payroll_task(self, payroll_run_id: int) -> dict:
    """
    Asynchronous Celery task that processes an entire payroll run.

    Returns immediately with a task ID. The actual computation runs
    in a background worker process — the HTTP request does not block.
    """
    from .services import process_payroll_run
    try:
        process_payroll_run(payroll_run_id)
        return {'status': 'completed', 'payroll_run_id': payroll_run_id}
    except Exception as exc:
        # Exponential back-off retry on transient failures
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def generate_invoice_pdf_task(self, payroll_entry_id: int) -> dict:
    """
    Generate a PDF invoice for a single payroll entry using ReportLab.

    CPU-bound — must never run in the Django request/response cycle.
    Saves the PDF to MEDIA_ROOT (or swap for GCS in production).
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT

        entry = PayrollEntry.objects.select_related(
            'worker', 'worker__agency', 'payroll_run'
        ).get(pk=payroll_entry_id)

        # Build PDF in memory
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        styles = getSampleStyleSheet()
        story = []

        # ── Title ─────────────────────────────────────────────────────────
        title_style = ParagraphStyle(
            'title', parent=styles['Heading1'],
            alignment=TA_CENTER, fontSize=22, spaceAfter=4,
            textColor=colors.HexColor('#4F46E5'),
        )
        story.append(Paragraph("PAYROLL INVOICE", title_style))
        story.append(Paragraph(
            f"{entry.worker.agency.name}", 
            ParagraphStyle('agency', parent=styles['Normal'], alignment=TA_CENTER, fontSize=11)
        ))
        story.append(Spacer(1, 0.5 * cm))

        # ── Worker & Period Info ──────────────────────────────────────────
        info_data = [
            ['Worker:', entry.worker.name, 'Period Start:', str(entry.payroll_run.period_start)],
            ['Email:', entry.worker.email, 'Period End:', str(entry.payroll_run.period_end)],
            ['Hourly Rate:', f"£{entry.worker.hourly_rate}", 'Invoice Date:', str(timezone.now().date())],
        ]
        info_table = Table(info_data, colWidths=[3.5*cm, 6*cm, 3.5*cm, 4.5*cm])
        info_table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 0.5 * cm))

        # ── Pay Breakdown Table ───────────────────────────────────────────
        pay_data = [
            ['Description', 'Hours', 'Rate', 'Amount'],
            ['Regular Pay', f"{entry.regular_hours:.2f}", f"£{entry.worker.hourly_rate:.2f}", f"£{entry.regular_pay:.2f}"],
            ['Overtime Pay (1.5x)', f"{entry.overtime_hours:.2f}", f"£{entry.worker.hourly_rate * Decimal('1.5'):.2f}", f"£{entry.overtime_pay:.2f}"],
            ['', '', 'TOTAL GROSS PAY', f"£{entry.total_pay:.2f}"],
        ]
        pay_table = Table(pay_data, colWidths=[8*cm, 3*cm, 4*cm, 3*cm])
        pay_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F46E5')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (2, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.HexColor('#F8F8FF'), colors.white]),
            ('BACKGROUND', (2, -1), (-1, -1), colors.HexColor('#EEF2FF')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E0E0')),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(pay_table)
        story.append(Spacer(1, 0.5 * cm))

        # ── Footer ────────────────────────────────────────────────────────
        story.append(Paragraph(
            "This payroll statement has been generated automatically. "
            "Please contact your agency administrator for any discrepancies.",
            ParagraphStyle('footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey)
        ))

        doc.build(story)

        # Save PDF to disk (swap for GCS bucket.blob().upload_from_file() in production)
        pdf_dir = os.path.join(settings.MEDIA_ROOT, 'invoices')
        os.makedirs(pdf_dir, exist_ok=True)
        filename = f"invoice_entry_{payroll_entry_id}.pdf"
        filepath = os.path.join(pdf_dir, filename)

        with open(filepath, 'wb') as f:
            f.write(buffer.getvalue())

        # Update entry with the PDF path
        entry.invoice_pdf_path = f"invoices/{filename}"
        entry.save(update_fields=['invoice_pdf_path'])

        AuditLog.objects.create(
            action='INVOICE_PDF_GENERATED',
            payload={'payroll_entry_id': payroll_entry_id, 'path': entry.invoice_pdf_path},
        )

        return {'status': 'pdf_generated', 'path': entry.invoice_pdf_path}

    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task
def dispatch_invoice_generation(payroll_run_id: int) -> None:
    """
    After a payroll run completes, fan out individual PDF generation tasks.
    Each worker's invoice is generated in parallel by separate Celery workers.
    """
    entry_ids = PayrollEntry.objects.filter(
        payroll_run_id=payroll_run_id
    ).values_list('id', flat=True)

    for entry_id in entry_ids:
        generate_invoice_pdf_task.delay(entry_id)
