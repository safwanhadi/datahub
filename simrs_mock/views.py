from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from verification.health_metadata import DISEASE_GROUPS

from .authentication import MockBearerAuthentication
from .serializers import (
    DiseaseEnvelopeSerializer,
    DiseaseGroupEnvelopeSerializer,
    PeriodQuerySerializer,
    TouristEnvelopeSerializer,
    VisitEnvelopeSerializer,
)


PERIOD_PARAMS = [
    OpenApiParameter("tgl_awal", str, required=True, description="Tanggal awal periode YYYY-MM-DD"),
    OpenApiParameter("tgl_akhir", str, required=True, description="Tanggal akhir periode YYYY-MM-DD"),
]
HOSPITAL = {"province_code": "52", "province_name": "Nusa Tenggara Barat", "code": "RS-MANDALIKA", "name": "RS Mandalika"}
INSTALLATION_COUNTS = {
    "outpatient": {"general": 120, "bpjs": 820, "private_insurance": 45, "social_assistance": 12, "other": 20},
    "inpatient": {"general": 30, "bpjs": 190, "private_insurance": 8, "social_assistance": 4, "other": 6},
    "emergency": {"general": 65, "bpjs": 210, "private_insurance": 12, "social_assistance": 7, "other": 11},
}
TOP_DISEASES = [
    ("J06.9", "Infeksi saluran pernapasan akut", 132), ("I10", "Hipertensi esensial", 118),
    ("E11.9", "Diabetes melitus tipe 2", 96), ("K30", "Dispepsia", 83),
    ("A09", "Gastroenteritis", 76), ("M54.5", "Nyeri punggung bawah", 68),
    ("J45.9", "Asma", 54), ("N39.0", "Infeksi saluran kemih", 47),
    ("R50.9", "Demam", 41), ("K21.9", "Refluks gastroesofagus", 38),
]


def _context(request):
    query = PeriodQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    start, end = query.validated_data["tgl_awal"], query.validated_data["tgl_akhir"]
    days = (end - start).days + 1
    if start.day == 1 and end.year == start.year and end.month == start.month:
        kind, label = "month", start.strftime("%Y-%m")
    elif start.month in (1, 4, 7, 10) and start.day == 1 and end.month == start.month + 2 and end.day in (30, 31):
        quarter = (start.month - 1) // 3 + 1; kind, label = "quarter", f"{start.year}-Q{quarter}"
    elif start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31 and end.year == start.year:
        kind, label = "year", str(start.year)
    elif start.month in (1, 7) and start.day == 1 and end.month == (6 if start.month == 1 else 12) and end.day in (30, 31) and end.year == start.year:
        semester = 1 if start.month == 1 else 2; kind, label = "semester", f"{start.year}-S{semester}"
    else:
        kind, label = "custom", f"{start.isoformat()} s.d. {end.isoformat()}"
    return {"type": kind, "label": label, "start": start, "end": end, "days": days}, HOSPITAL


def _visits(installation=None):
    return [
        {"installation": key, "payment_status": payment, "count": count}
        for key, payments in INSTALLATION_COUNTS.items() if installation is None or key == installation
        for payment, count in payments.items()
    ]


def _diseases():
    return [
        {"installation": installation, "icd10_code": code, "name": name, "patient_count": max(count - offset, 1)}
        for installation, offset in (("outpatient", 0), ("inpatient", 35), ("emergency", 55))
        for code, name, count in TOP_DISEASES
    ]


def _tourists():
    return [
        {"category": "international", "origin": "Australia", "count": 18},
        {"category": "international", "origin": "Malaysia", "count": 7},
        {"category": "domestic", "origin": "Bali", "count": 31},
        {"category": "domestic", "origin": "Jawa Timur", "count": 24},
    ]


def _groups():
    counts = {"cancer": 42, "heart": 76, "stroke": 31, "uronephrology": 58}
    return [{"code": code, "icd10_range": icd_range, "patient_count": counts[code]} for code, icd_range in DISEASE_GROUPS.items()]


class MockBaseView(APIView):
    authentication_classes = (MockBearerAuthentication,)


class VisitView(MockBaseView):
    @extend_schema(tags=["Kunjungan Rawat Jalan, Rawat Inap, dan IGD"], parameters=PERIOD_PARAMS, responses=VisitEnvelopeSerializer)
    def get(self, request):
        period, hospital = _context(request)
        return Response({"period": period, "hospital": hospital, "results": _visits()})


class TopDiseasesView(MockBaseView):
    @extend_schema(tags=["10 Penyakit Terbanyak"], parameters=PERIOD_PARAMS, responses=DiseaseEnvelopeSerializer)
    def get(self, request):
        period, hospital = _context(request)
        return Response({"period": period, "hospital": hospital, "results": _diseases()})


class TouristVisitsView(MockBaseView):
    @extend_schema(tags=["Kunjungan Wisatawan"], parameters=PERIOD_PARAMS, responses=TouristEnvelopeSerializer)
    def get(self, request):
        period, hospital = _context(request)
        return Response({"period": period, "hospital": hospital, "results": _tourists()})


class DiseaseGroupView(MockBaseView):
    @extend_schema(tags=["Pasien Kanker, Jantung, Stroke, dan Uronefrologi"], parameters=PERIOD_PARAMS, responses=DiseaseGroupEnvelopeSerializer)
    def get(self, request):
        period, hospital = _context(request)
        return Response({"period": period, "hospital": hospital, "results": _groups()})
