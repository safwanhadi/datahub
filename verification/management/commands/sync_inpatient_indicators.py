from datetime import date

from django.core.management.base import BaseCommand, CommandError

from verification.services import fetch_inpatient_indicator


class Command(BaseCommand):
    help = "Ambil JSON indikator bulanan dari PHP dan hitung ulang di Django."

    def add_arguments(self, parser):
        parser.add_argument("--period", required=True, help="Periode YYYY-MM")

    def handle(self, *args, **options):
        try:
            year, month = (int(value) for value in options["period"].split("-", 1))
            period = date(year, month, 1)
        except (TypeError, ValueError):
            raise CommandError("Periode harus menggunakan format YYYY-MM.")
        source = fetch_inpatient_indicator(period=period)
        self.stdout.write(
            self.style.SUCCESS(
                f"Sinkronisasi {source.period:%Y-%m} selesai: "
                f"BOR {source.bor}, ALOS {source.alos}."
            )
        )
