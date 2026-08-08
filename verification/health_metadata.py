from copy import deepcopy

from django.core.exceptions import ValidationError

INSTALLATIONS = {"emergency", "inpatient", "outpatient"}
PAYMENT_STATUSES = {"general", "bpjs", "private_insurance", "social_assistance", "other"}
TOURIST_CATEGORIES = {"international", "domestic"}
DISEASE_GROUPS = {"cancer": "C00-C96,D00-D48", "heart": "I00-I52", "stroke": "I60-I69", "uronephrology": "N00-N39"}
HEALTH_INDICATORS = {
    "outpatient-visits": {"name": "Kunjungan Rawat Jalan", "unit": "orang"},
    "inpatient-visits": {"name": "Kunjungan Rawat Inap", "unit": "orang"},
    "emergency-visits": {"name": "Kunjungan IGD", "unit": "orang"},
    "top-diseases": {"name": "10 Penyakit Terbanyak", "unit": "kasus"},
    "tourist-visits": {"name": "Kunjungan Wisatawan", "unit": "orang"},
    "cancer-patients": {"name": "Pasien Kanker", "unit": "orang"},
    "heart-patients": {"name": "Pasien Jantung", "unit": "orang"},
    "stroke-patients": {"name": "Pasien Stroke", "unit": "orang"},
    "uronephrology-patients": {"name": "Pasien Uronefrologi", "unit": "orang"},
}

# Unit kerja verifikator. Empat indikator penyakit prioritas dinilai sebagai
# satu kesatuan KJSU, tetapi kontrak API publiknya tetap berupa empat endpoint.
HEALTH_VERIFICATION_GROUPS = {
    "outpatient-visits": HEALTH_INDICATORS["outpatient-visits"],
    "inpatient-visits": HEALTH_INDICATORS["inpatient-visits"],
    "emergency-visits": HEALTH_INDICATORS["emergency-visits"],
    "top-diseases": HEALTH_INDICATORS["top-diseases"],
    "tourist-visits": HEALTH_INDICATORS["tourist-visits"],
    "kjsu-evaluation": {
        "name": "Evaluasi KJSU",
        "unit": "orang",
        "description": "Kanker, Jantung, Stroke, dan Uronefrologi",
    },
}


def verification_group_for_indicator(code):
    if code in {
        "cancer-patients", "heart-patients", "stroke-patients",
        "uronephrology-patients",
    }:
        return "kjsu-evaluation"
    return code

def _count(value, path):
    if isinstance(value, bool):
        raise ValidationError(f"{path} harus berupa bilangan bulat non-negatif.")
    try: value = int(value)
    except (TypeError, ValueError) as exc: raise ValidationError(f"{path} harus berupa bilangan bulat non-negatif.") from exc
    if value < 0: raise ValidationError(f"{path} tidak boleh negatif.")
    return value

def normalize_health_payload(payload):
    if not isinstance(payload, dict): raise ValidationError("Respons indikator kesehatan harus berupa objek JSON.")
    result = deepcopy(payload); hospital = result.get("hospital")
    if not isinstance(hospital, dict) or not hospital.get("code") or not hospital.get("name"): raise ValidationError("hospital.code dan hospital.name wajib tersedia.")
    visits = result.get("visits", [])
    if not isinstance(visits, list): raise ValidationError("visits harus berupa array.")
    for i, row in enumerate(visits):
        if row.get("installation") not in INSTALLATIONS: raise ValidationError(f"visits[{i}].installation tidak valid.")
        if row.get("payment_status") not in PAYMENT_STATUSES: raise ValidationError(f"visits[{i}].payment_status tidak valid.")
        row["count"] = _count(row.get("count"), f"visits[{i}].count")
    diseases = result.get("top_diseases", [])
    if not isinstance(diseases, list): raise ValidationError("top_diseases harus berupa array.")
    counters = {key: 0 for key in INSTALLATIONS}
    for i, row in enumerate(diseases):
        installation = row.get("installation")
        if installation not in INSTALLATIONS: raise ValidationError(f"top_diseases[{i}].installation tidak valid.")
        if not row.get("icd10_code") or not row.get("name"): raise ValidationError(f"top_diseases[{i}] wajib memiliki kode dan nama penyakit.")
        row["patient_count"] = _count(row.get("patient_count"), f"top_diseases[{i}].patient_count")
        counters[installation] += 1
        if counters[installation] > 10: raise ValidationError(f"Top penyakit {installation} maksimal 10 baris.")
    tourists = result.get("tourist_visits", [])
    if not isinstance(tourists, list): raise ValidationError("tourist_visits harus berupa array.")
    for i, row in enumerate(tourists):
        if row.get("category") not in TOURIST_CATEGORIES: raise ValidationError(f"tourist_visits[{i}].category tidak valid.")
        row["count"] = _count(row.get("count"), f"tourist_visits[{i}].count")
    groups = result.get("disease_groups", []); seen = set()
    if not isinstance(groups, list): raise ValidationError("disease_groups harus berupa array.")
    for i, row in enumerate(groups):
        code = row.get("code")
        if code not in DISEASE_GROUPS or code in seen: raise ValidationError(f"disease_groups[{i}].code tidak valid atau duplikat.")
        seen.add(code); row["icd10_range"] = DISEASE_GROUPS[code]; row["patient_count"] = _count(row.get("patient_count"), f"disease_groups[{i}].patient_count")
    # Indikator kepuasan pasien dikelola langsung oleh Diskominfotik dan tidak
    # menjadi bagian dari pengumpulan maupun penyimpanan DataHub rumah sakit.
    result.pop("patient_satisfaction", None)
    return result

def indicator_payload(data, code):
    if code not in HEALTH_INDICATORS: raise KeyError(code)
    installation_by_code = {"outpatient-visits": "outpatient", "inpatient-visits": "inpatient", "emergency-visits": "emergency"}
    if code in installation_by_code:
        rows = [row for row in data.get("visits", []) if row["installation"] == installation_by_code[code]]
        return {"total": sum(row["count"] for row in rows), "breakdown": rows}
    if code == "top-diseases": return {"results": data.get("top_diseases", [])}
    if code == "tourist-visits":
        rows = data.get("tourist_visits", []); return {"total": sum(row["count"] for row in rows), "breakdown": rows}
    group = code.removesuffix("-patients")
    return next((row for row in data.get("disease_groups", []) if row["code"] == group), None)
