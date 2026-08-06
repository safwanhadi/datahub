from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from verification.models import VerifiedInpatientIndicator, VerifiedMonthlyHealthIndicator, VerifiedRecord

from .serializers import (
    InternalIndicatorEnvelopeSerializer,
    InternalMonthlyHealthEnvelopeSerializer,
    InternalRecordEnvelopeSerializer,
)


PERIOD_PARAMETERS = [
    OpenApiParameter("tahun", int, description="Tahun laporan, contoh 2026"),
    OpenApiParameter("bulan", int, description="Bulan laporan 1–12"),
]


class InternalIndicatorList(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["Internal - Indikator"],
        parameters=PERIOD_PARAMETERS,
        responses=InternalIndicatorEnvelopeSerializer,
    )
    def get(self, request):
        records = VerifiedInpatientIndicator.objects.select_related("verified_by", "source")
        if request.query_params.get("tahun"):
            records = records.filter(period__year=request.query_params["tahun"])
        if request.query_params.get("bulan"):
            records = records.filter(period__month=request.query_params["bulan"])
        results = [
            {
                "periode": item.period,
                "jenis_periode": item.source.period_type,
                "tanggal_awal": item.source.period_start,
                "tanggal_akhir": item.source.period_end,
                "status": item.status,
                "alos": item.alos,
                "bor": item.bor,
                "bto": item.bto,
                "toi": item.toi,
                "gdr": item.gdr,
                "ndr": item.ndr,
                "notes": item.notes,
                "verified_by": item.verified_by.get_username() if item.verified_by else None,
                "verified_at": item.verified_at,
                "updated_at": item.updated_at,
            }
            for item in records
        ]
        return Response({"count": len(results), "results": results})


class InternalVerifiedRecordList(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["Internal - Data Terverifikasi"],
        parameters=[OpenApiParameter("limit", int, description="Maksimal 500")],
        responses=InternalRecordEnvelopeSerializer,
    )
    def get(self, request, record_type):
        try:
            limit = min(max(int(request.query_params.get("limit", 100)), 1), 500)
        except ValueError:
            return Response({"detail": "Parameter limit harus berupa angka."}, status=400)
        records = VerifiedRecord.objects.filter(
            staged_record__record_type=record_type
        ).select_related("staged_record", "verified_by")[:limit]
        results = [
            {
                "id": item.id,
                "record_type": item.staged_record.record_type,
                "source_key": item.staged_record.source_key,
                "status": item.status,
                "data": item.verified_data,
                "verified_by": item.verified_by.get_username() if item.verified_by else None,
                "approved_at": item.approved_at,
                "updated_at": item.updated_at,
            }
            for item in records
        ]
        return Response({"record_type": record_type, "count": len(results), "results": results})


class InternalMonthlyHealthList(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    @extend_schema(tags=["Internal - Indikator Kesehatan"], parameters=PERIOD_PARAMETERS, responses=InternalMonthlyHealthEnvelopeSerializer)
    def get(self, request):
        records = VerifiedMonthlyHealthIndicator.objects.select_related("source", "verified_by").prefetch_related("visit_rows", "top_disease_rows", "tourist_visit_rows", "disease_group_rows")
        if request.query_params.get("tahun"): records = records.filter(period__year=request.query_params["tahun"])
        if request.query_params.get("bulan"): records = records.filter(period__month=request.query_params["bulan"])
        results = [{"periode": item.period, "jenis_periode": item.source.period_type, "tanggal_awal": item.source.period_start, "tanggal_akhir": item.source.period_end, "status": item.status, "hospital_code": item.source.hospital_code, "hospital_name": item.source.hospital_name, "data": item.to_payload(), "verified_by": item.verified_by.get_username() if item.verified_by else None, "verified_at": item.verified_at} for item in records]
        return Response({"count": len(results), "results": results})
