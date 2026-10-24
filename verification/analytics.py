from decimal import Decimal
from types import SimpleNamespace


def summarize_inpatient_records(records, period_start, period_end):
    """Use an exact verified period, otherwise combine nonoverlapping monthly working data."""
    records = list(records)
    exact = next((r for r in records if r.source.period_start == period_start
                  and r.source.period_end == period_end), None)
    if exact:
        selected = [exact]
    else:
        selected = sorted((r for r in records if r.source.period_type == "month"),
                          key=lambda r: r.source.period_start)
        selected = [r for i, r in enumerate(selected)
                    if i == 0 or r.source.period_start > selected[i - 1].source.period_end]
    if not selected:
        return None
    days = sum(r.working_days_in_period for r in selected)
    capacity = sum(Decimal(r.working_beds) * r.working_days_in_period for r in selected)
    if len(selected) == 1:
        values = {code: getattr(selected[0], code) for code in INPATIENT_STANDARDS}
    else:
        care = Decimal(sum(r.working_care_days for r in selected))
        discharged = Decimal(sum(r.working_discharged_patients for r in selected) or 1)
        beds = capacity / Decimal(days or 1)
        values = {
            "alos": care / discharged,
            "bor": care / (capacity or 1) * 100,
            "bto": Decimal(sum(r.working_discharged_patients for r in selected)) / (beds or 1),
            "toi": (capacity - care) / discharged,
            "gdr": Decimal(sum(r.working_deaths for r in selected)) / discharged * 1000,
            "ndr": Decimal(sum(r.working_deaths_over_48h for r in selected)) / discharged * 1000,
        }
        values = {k: v.quantize(Decimal("0.01")) for k, v in values.items()}
    covered_days = sum((r.source.period_end - r.source.period_start).days + 1 for r in selected)
    return SimpleNamespace(
        source=SimpleNamespace(days_in_period=days, period_start=period_start, period_end=period_end),
        period=period_start, covered_days=covered_days,
        expected_days=(period_end - period_start).days + 1, **values,
    )


INPATIENT_STANDARDS = {
    "alos": {
        "name": "ALOS", "description": "Rata-rata lama dirawat", "unit": "hari",
        "minimum": Decimal("6"), "maximum": Decimal("9"), "standard": "6–9 hari",
        "low": "Lama rawat lebih singkat dari acuan. Tinjau case mix, kesinambungan perawatan, dan potensi rawat ulang.",
        "high": "Lama rawat melebihi acuan. Tinjau hambatan klinis, penunjang, dan perencanaan pemulangan.",
    },
    "bor": {
        "name": "BOR", "description": "Pemanfaatan tempat tidur", "unit": "%",
        "minimum": Decimal("60"), "maximum": Decimal("85"), "standard": "60–85%",
        "low": "Pemanfaatan tempat tidur di bawah acuan. Evaluasi permintaan layanan dan alokasi kapasitas.",
        "high": "Okupansi melampaui acuan. Waspadai kepadatan, waktu tunggu, dan beban tenaga pelayanan.",
    },
    "bto": {
        "name": "BTO", "description": "Frekuensi penggunaan tempat tidur", "unit": "kali",
        "minimum": Decimal("40"), "maximum": Decimal("50"), "standard": "40–50 kali/tahun",
        "low": "Perputaran tempat tidur di bawah acuan tahunan. Evaluasi utilisasi kapasitas rawat inap.",
        "high": "Perputaran tempat tidur di atas acuan tahunan. Tinjau beban tempat tidur dan mutu transisi pasien.",
    },
    "toi": {
        "name": "TOI", "description": "Jeda tempat tidur kosong", "unit": "hari",
        "minimum": Decimal("1"), "maximum": Decimal("3"), "standard": "1–3 hari",
        "low": "Jeda penggunaan sangat singkat. Pastikan kesiapan tempat tidur dan prosedur pencegahan infeksi.",
        "high": "Tempat tidur kosong lebih lama dari acuan. Evaluasi distribusi kapasitas dan alur admisi.",
    },
    "gdr": {
        "name": "GDR", "description": "Kematian umum pasien keluar", "unit": "‰",
        "maximum": Decimal("45"), "standard": "≤45 per 1.000",
        "high": "Angka kematian umum melebihi batas acuan. Lakukan telaah mortalitas dan case mix secara klinis.",
    },
    "ndr": {
        "name": "NDR", "description": "Kematian ≥48 jam", "unit": "‰",
        "maximum_exclusive": Decimal("25"), "standard": "<25 per 1.000",
        "high": "Angka kematian setelah 48 jam mencapai atau melebihi batas. Prioritaskan audit mutu klinis.",
    },
}


def analyze_inpatient_record(record, standards=None, *, period_fraction=None, period_label=None):
    """Bandingkan hasil verifikasi dengan acuan Kemenkes secara aman per periode."""
    results = []
    standards = standards or {}
    for code, default_meta in INPATIENT_STANDARDS.items():
        meta = default_meta.copy()
        configured = standards.get(code)
        if configured:
            meta.pop("minimum", None)
            meta.pop("maximum", None)
            meta.pop("maximum_exclusive", None)
            if configured.minimum_value is not None:
                meta["minimum"] = configured.minimum_value
            if configured.maximum_value is not None:
                key = "maximum_exclusive" if configured.maximum_exclusive else "maximum"
                meta[key] = configured.maximum_value
            meta["unit"] = configured.unit
            lower = f"{configured.minimum_value:g}" if configured.minimum_value is not None else None
            upper = f"{configured.maximum_value:g}" if configured.maximum_value is not None else None
            if lower and upper:
                meta["standard"] = f"{lower}–{upper} {configured.unit}"
            elif upper:
                operator = "<" if configured.maximum_exclusive else "≤"
                meta["standard"] = f"{operator}{upper} {configured.unit}"
            else:
                meta["standard"] = f"≥{lower} {configured.unit}"
            if configured.period_basis == "annual":
                meta["standard"] += "/tahun"
            meta["policy_level"] = configured.get_policy_level_display()
            meta["reference_name"] = configured.reference_name
            meta["reference_url"] = configured.reference_url

        value = Decimal(getattr(record, code))
        comparison_value = value
        comparison_note = ""
        annualize = configured.period_basis == "annual" if configured else code == "bto"
        if annualize and period_fraction is not None:
            annual_standard = meta["standard"]
            for bound in ("minimum", "maximum", "maximum_exclusive"):
                if bound in meta:
                    meta[bound] *= period_fraction
            lower = meta.get("minimum")
            upper = meta.get("maximum", meta.get("maximum_exclusive"))
            if lower is not None and upper is not None:
                meta["standard"] = f"{lower:.2f}–{upper:.2f} {meta['unit']}/{period_label}"
            elif upper is not None:
                operator = "<" if "maximum_exclusive" in meta else "≤"
                meta["standard"] = f"{operator}{upper:.2f} {meta['unit']}/{period_label}"
            elif lower is not None:
                meta["standard"] = f"≥{lower:.2f} {meta['unit']}/{period_label}"
            comparison_note = (
                f"Standar satu tahun penuh: {annual_standard}. "
                "Acuan periode dikonversi proporsional terhadap jumlah hari data terverifikasi."
            )
            annualize = False
            meta["low"] = meta.get("low", "Nilai di bawah acuan periode.").replace("acuan tahunan", "acuan periode")
            meta["high"] = meta.get("high", "Nilai di atas acuan periode.").replace("acuan tahunan", "acuan periode")
        if annualize and record.source.days_in_period:
            comparison_value = value * Decimal("365") / Decimal(record.source.days_in_period)
            if record.source.days_in_period < 365:
                comparison_note = f"Proyeksi tahunan {comparison_value:.1f} kali dari periode {record.source.days_in_period} hari."

        if "minimum" in meta and comparison_value < meta["minimum"]:
            level, label, analysis = "low", "Di bawah standar", meta["low"]
        elif (
            ("maximum" in meta and comparison_value > meta["maximum"])
            or ("maximum_exclusive" in meta and comparison_value >= meta["maximum_exclusive"])
        ):
            level, label, analysis = "high", "Di atas standar", meta["high"]
        else:
            level, label = "ideal", "Sesuai standar"
            analysis = "Nilai berada dalam batas acuan. Pertahankan mutu dan pantau konsistensi antarperiode."

        results.append({
            "code": code, "value": value, "level": level, "label": label,
            "comparison_note": comparison_note, "analysis": analysis,
            "policy_level": meta.get("policy_level", "Kebijakan nasional"),
            "reference_name": meta.get("reference_name", "Petunjuk Teknis Kementerian Kesehatan"),
            "reference_url": meta.get("reference_url", ""), **meta,
        })
    return results


def get_applicable_standards(period):
    """Ambil satu kebijakan per indikator; kebijakan internal mengungguli nasional."""
    from django.db.models import Case, IntegerField, Q, Value, When
    from .models import InpatientIndicatorStandard

    candidates = InpatientIndicatorStandard.objects.filter(
        is_active=True,
        effective_from__lte=period,
    ).filter(Q(effective_until__isnull=True) | Q(effective_until__gte=period)).annotate(
        policy_priority=Case(
            When(policy_level=InpatientIndicatorStandard.PolicyLevel.INTERNAL, then=Value(0)),
            default=Value(1), output_field=IntegerField(),
        )
    ).order_by("indicator", "policy_priority", "-effective_from", "-updated_at")
    selected = {}
    for standard in candidates:
        selected.setdefault(standard.indicator, standard)
    return selected
