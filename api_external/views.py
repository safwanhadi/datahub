from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from api_access.authentication import SimaduOpaqueTokenAuthentication
from api_access.mixins import ExternalApiAuditMixin
from api_access.permissions import HasExternalApiGrant
from api_access.throttling import ExternalClientRateThrottle
from verification.health_metadata import HEALTH_INDICATORS, indicator_payload
from verification.models import VerifiedInpatientIndicator, VerifiedMonthlyHealthIndicator
from verification.views import INDICATOR_META

from .serializers import ExternalHealthIndicatorEnvelopeSerializer, ExternalIndicatorEnvelopeSerializer


def _period_fields(source):
    start = source.period_start or source.period
    end = source.period_end or source.period
    return {
        "periode": f"{start:%Y-%m-%d}/{end:%Y-%m-%d}",
        "jenis_periode": source.period_type,
        "tanggal_awal": start,
        "tanggal_akhir": end,
    }


class ExternalApiView(ExternalApiAuditMixin, APIView):
    authentication_classes = (SimaduOpaqueTokenAuthentication,)
    permission_classes = (HasExternalApiGrant,)
    throttle_classes = (ExternalClientRateThrottle,)


class ExternalIndicatorList(ExternalApiView):
    def get_api_product_code(self):
        return f"indicator-{self.kwargs['indicator']}"

    @extend_schema(
        tags=["Eksternal - Indikator"],
        parameters=[
            OpenApiParameter(
                "indicator",
                str,
                location=OpenApiParameter.PATH,
                enum=list(INDICATOR_META),
            ),
            OpenApiParameter("tahun", int, description="Tahun laporan, contoh 2026"),
            OpenApiParameter("bulan", int, description="Bulan laporan 1–12"),
        ],
        responses=ExternalIndicatorEnvelopeSerializer,
    )
    def get(self, request, indicator):
        if indicator not in INDICATOR_META:
            return Response({"detail": "Indikator tidak ditemukan."}, status=404)
        records = VerifiedInpatientIndicator.objects.select_related("source").filter(
            status=VerifiedInpatientIndicator.Status.APPROVED
        )
        if request.query_params.get("tahun"):
            records = records.filter(period__year=request.query_params["tahun"])
        if request.query_params.get("bulan"):
            records = records.filter(period__month=request.query_params["bulan"])
        name, unit = INDICATOR_META[indicator]
        results = [
            {
                **_period_fields(item.source),
                "nilai": getattr(item, indicator),
                "diverifikasi_pada": item.verified_at,
            }
            for item in records
        ]
        return Response(
            {
                "indikator": indicator.upper(),
                "nama": name,
                "satuan": unit,
                "count": len(results),
                "results": results,
            }
        )


class ExternalHealthIndicatorList(ExternalApiView):
    def get_api_product_code(self):
        return f"health-{self.kwargs['code']}"

    @extend_schema(
        tags=["Eksternal - Indikator Kesehatan"],
        parameters=[
            OpenApiParameter("code", str, location=OpenApiParameter.PATH, enum=list(HEALTH_INDICATORS)),
            OpenApiParameter("tahun", int), OpenApiParameter("bulan", int),
        ],
        responses=ExternalHealthIndicatorEnvelopeSerializer,
    )
    def get(self, request, code):
        if code not in HEALTH_INDICATORS:
            return Response({"detail": "Indikator tidak ditemukan."}, status=404)
        records = VerifiedMonthlyHealthIndicator.objects.select_related("source").prefetch_related("visit_rows", "top_disease_rows", "tourist_visit_rows", "disease_group_rows").filter(status=VerifiedMonthlyHealthIndicator.Status.APPROVED)
        if request.query_params.get("tahun"): records = records.filter(period__year=request.query_params["tahun"])
        if request.query_params.get("bulan"): records = records.filter(period__month=request.query_params["bulan"])
        results = [{**_period_fields(item.source), "data": indicator_payload(item.to_payload(), code), "diverifikasi_pada": item.verified_at} for item in records]
        meta = HEALTH_INDICATORS[code]
        return Response({"kode": code, "nama": meta["name"], "satuan": meta["unit"], "count": len(results), "results": results})
