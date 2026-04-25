"""DRF serializers for the payroll app."""
from rest_framework import serializers
from .models import Agency, Worker, Shift, PayrollRun, PayrollEntry


class AgencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Agency
        fields = ['id', 'name', 'created_at']


class WorkerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Worker
        fields = ['id', 'agency', 'name', 'email', 'hourly_rate', 'weekly_hours_threshold', 'created_at']


class ShiftSerializer(serializers.ModelSerializer):
    hours_worked = serializers.SerializerMethodField()

    class Meta:
        model = Shift
        fields = ['id', 'worker', 'start_time', 'end_time', 'status', 'notes', 'hours_worked', 'created_at']

    def get_hours_worked(self, obj):
        return float(obj.hours_worked())

    def validate(self, attrs):
        if attrs.get('end_time') and attrs.get('start_time'):
            if attrs['end_time'] <= attrs['start_time']:
                raise serializers.ValidationError("end_time must be after start_time.")
        return attrs


class PayrollEntrySerializer(serializers.ModelSerializer):
    worker_name = serializers.CharField(source='worker.name', read_only=True)
    worker_email = serializers.CharField(source='worker.email', read_only=True)
    hourly_rate = serializers.DecimalField(source='worker.hourly_rate', max_digits=8, decimal_places=2, read_only=True)

    class Meta:
        model = PayrollEntry
        fields = [
            'id', 'worker', 'worker_name', 'worker_email', 'hourly_rate',
            'regular_hours', 'overtime_hours', 'regular_pay', 'overtime_pay',
            'total_pay', 'invoice_pdf_path', 'created_at',
        ]


class PayrollRunSerializer(serializers.ModelSerializer):
    entries = PayrollEntrySerializer(many=True, read_only=True)
    total_payroll_cost = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = [
            'id', 'agency', 'period_start', 'period_end', 'status',
            'celery_task_id', 'error_message', 'created_at', 'completed_at',
            'entries', 'total_payroll_cost',
        ]
        read_only_fields = ['status', 'celery_task_id', 'error_message', 'completed_at']

    def get_total_payroll_cost(self, obj):
        total = sum(e.total_pay for e in obj.entries.all())
        return float(total)


class PayrollRunCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollRun
        fields = ['agency', 'period_start', 'period_end']

    def validate(self, attrs):
        if attrs['period_end'] <= attrs['period_start']:
            raise serializers.ValidationError("period_end must be after period_start.")
        return attrs
