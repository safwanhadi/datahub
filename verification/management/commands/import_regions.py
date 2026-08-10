import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connection
from django.db.models import Q

from verification.models import AdministrativeRegion, RegionAlias, VerifiedTouristVisitRow, normalize_region_name
from verification.services import reprocess_region_mappings


LOMBOK_CODES = ("52.01", "52.02", "52.03", "52.08", "52.71")
DEFAULT_ALIASES = {
    "52.01": ("LOBAR",),
    "52.02": ("LOTENG", "LOTEN", "LOYTENG", "LOOTENG", "LMBOK TENGAH", "LOITENG", "LOTRNG", "LOTNG"),
    "52.03": ("LOTIM",),
    "52.71": ("MATARAM", "KOTA MATARAM"),
    "52.02.04": ("PUJUT",),
}


def region_type(code, name):
    depth = len(code.split("."))
    if depth == 1:
        return AdministrativeRegion.RegionType.PROVINCE
    if depth == 2:
        return AdministrativeRegion.RegionType.CITY if name.casefold().startswith("kota ") else AdministrativeRegion.RegionType.REGENCY
    if depth == 3:
        return AdministrativeRegion.RegionType.DISTRICT
    if depth == 4:
        return AdministrativeRegion.RegionType.VILLAGE
    return AdministrativeRegion.RegionType.OTHER


class Command(BaseCommand):
    help = "Impor master wilayah resmi dari CSV secara idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default=str(Path(settings.BASE_DIR) / "docs" / "wilayah_full.csv"),
            help="Lokasi CSV dengan kolom kode,nama.",
        )

    def handle(self, *args, **options):
        path = Path(options["file"]).resolve()
        if not path.is_file():
            raise CommandError(f"File master wilayah tidak ditemukan: {path}")

        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames or not {"kode", "nama"}.issubset(reader.fieldnames):
                raise CommandError("CSV wajib memiliki kolom kode dan nama.")
            rows = [
                (str(row["kode"]).strip(), str(row["nama"]).strip())
                for row in reader if row.get("kode") and row.get("nama")
            ]

        existing_codes = set(AdministrativeRegion.objects.values_list("official_code", flat=True))
        new_objects = [
            AdministrativeRegion(
                official_code=code,
                name=name,
                normalized_name=normalize_region_name(name),
                region_type=region_type(code, name),
                island_group="Lombok" if any(code == root or code.startswith(f"{root}.") for root in LOMBOK_CODES) else "",
            )
            for code, name in rows if code not in existing_codes
        ]
        AdministrativeRegion.objects.bulk_create(new_objects, batch_size=500, ignore_conflicts=True)

        # Hindari klausa IN berisi puluhan ribu parameter yang melampaui batas
        # paket/query sebagian server MySQL.
        connection.close()
        close_old_connections()
        if connection.vendor == "mysql":
            table = connection.ops.quote_name(AdministrativeRegion._meta.db_table)
            with connection.cursor() as cursor:
                for depth in (1, 2, 3):
                    cursor.execute(
                        f"UPDATE {table} child JOIN {table} parent "
                        f"ON parent.official_code = SUBSTRING_INDEX(child.official_code, '.', %s) "
                        f"SET child.parent_id = parent.id "
                        f"WHERE (LENGTH(child.official_code) - LENGTH(REPLACE(child.official_code, '.', ''))) = %s",
                        (depth, depth),
                    )
        else:
            regions = {item.official_code: item for item in AdministrativeRegion.objects.all()}
            updates = []
            for code, _ in rows:
                item = regions[code]
                parent_code = code.rpartition(".")[0] or None
                expected_parent = regions[parent_code].pk if parent_code in regions else None
                if item.parent_id != expected_parent:
                    item.parent_id = expected_parent
                    updates.append(item)
            AdministrativeRegion.objects.bulk_update(updates, ("parent",), batch_size=500)

        lombok_query = Q()
        for root in LOMBOK_CODES:
            lombok_query |= Q(official_code=root) | Q(official_code__startswith=f"{root}.")
        AdministrativeRegion.objects.filter(lombok_query).update(island_group="Lombok")
        for official_code, aliases in DEFAULT_ALIASES.items():
            region = AdministrativeRegion.objects.get(official_code=official_code)
            for alias_name in aliases:
                normalized_alias = normalize_region_name(alias_name)
                RegionAlias.objects.update_or_create(
                    normalized_alias=normalized_alias,
                    defaults={
                        "region": region, "alias": alias_name,
                        "source_system": "SIMRS", "is_active": True,
                    },
                )
        # Nama desa yang kebetulan sama dengan istilah umum tidak boleh menjadi
        # hasil cleaning tanpa kode resmi dari SIMRS.
        VerifiedTouristVisitRow.objects.filter(
            cleaning_method="exact_name", region__region_type="village"
        ).update(region=None, cleaning_method="unresolved")
        reprocess_region_mappings()
        self.stdout.write(self.style.SUCCESS(
            f"Impor selesai: {len(rows)} wilayah diproses, {len(new_objects)} wilayah baru dibuat, "
            f"{sum(map(len, DEFAULT_ALIASES.values()))} alias contoh diterapkan."
        ))
