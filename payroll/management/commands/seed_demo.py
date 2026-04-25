"""
Management command to seed the database with realistic demo data.

Creates 1 agency, 5 workers with varying rates, and 200 completed shifts
spread across the last 4 weeks — sufficient to demonstrate payroll processing
and overtime calculation.
"""
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from payroll.models import Agency, Worker, Shift


WORKERS_DATA = [
    {"name": "Alice Johnson", "email": "alice@sunrise.care", "hourly_rate": "14.50", "weekly_hours_threshold": 40},
    {"name": "Bob Smith",     "email": "bob@sunrise.care",   "hourly_rate": "13.00", "weekly_hours_threshold": 35},
    {"name": "Carol Davis",   "email": "carol@sunrise.care", "hourly_rate": "15.75", "weekly_hours_threshold": 40},
    {"name": "David Lee",     "email": "david@sunrise.care", "hourly_rate": "12.50", "weekly_hours_threshold": 40},
    {"name": "Emma Wilson",   "email": "emma@sunrise.care",  "hourly_rate": "16.00", "weekly_hours_threshold": 37},
]

SHIFT_HOURS = [4, 6, 8, 9, 10, 12]  # Variety — some will trigger overtime


class Command(BaseCommand):
    help = "Seed the database with demo payroll data"

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("🌱 Seeding database...")

        agency, _ = Agency.objects.get_or_create(name="Sunrise Care Agency")
        self.stdout.write(f"  ✓ Agency: {agency.name}")

        workers = []
        for wd in WORKERS_DATA:
            worker, _ = Worker.objects.get_or_create(
                email=wd["email"],
                defaults={
                    "agency": agency,
                    "name": wd["name"],
                    "hourly_rate": Decimal(wd["hourly_rate"]),
                    "weekly_hours_threshold": wd["weekly_hours_threshold"],
                },
            )
            workers.append(worker)
        self.stdout.write(f"  ✓ {len(workers)} workers created")

        # Generate 200 completed shifts across the last 4 weeks
        now = datetime.now(tz=timezone.utc)
        shifts_to_create = []
        count = 0

        for day_offset in range(28, 0, -1):
            shift_date = now - timedelta(days=day_offset)
            # 1-3 shifts per day, randomly assigned to workers
            for _ in range(random.randint(1, 3)):
                worker = random.choice(workers)
                hours = random.choice(SHIFT_HOURS)
                start = shift_date.replace(
                    hour=random.choice([6, 8, 9, 12, 14]),
                    minute=0, second=0, microsecond=0
                )
                end = start + timedelta(hours=hours)
                shifts_to_create.append(
                    Shift(
                        worker=worker,
                        start_time=start,
                        end_time=end,
                        status=Shift.Status.COMPLETED,
                        notes=f"Auto-seeded shift for {worker.name}",
                    )
                )
                count += 1
                if count >= 200:
                    break
            if count >= 200:
                break

        Shift.objects.bulk_create(shifts_to_create, ignore_conflicts=True)
        self.stdout.write(f"  ✓ {len(shifts_to_create)} shifts created")

        self.stdout.write(self.style.SUCCESS(
            "\n🎉 Seed complete!\n"
            "  Agency ID:  check /api/agencies/\n"
            "  Now POST to /api/payroll-runs/ to trigger async processing."
        ))
