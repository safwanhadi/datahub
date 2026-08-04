import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import ImportForm, IndicatorPeriodForm, InpatientIndicatorVerificationForm, VerificationForm
from .models import ImportBatch, InpatientIndicatorSource, StagedRecord, VerifiedInpatientIndicator, VerifiedRecord
from .oauth import (
    InsufficientScope,
    InvalidAccessToken,
    OAuthServerUnavailable,
    introspect_access_token,
)
from .services import begin_verification, fetch_inpatient_indicator, import_records, save_inpatient_verification, save_verification


@login_required
def dashboard(request):
    counts = {
        row["status"]: row["total"]
        for row in StagedRecord.objects.values("status").annotate(total=Count("id"))
    }
    context = {
        "counts": counts,
        "recent_batches": ImportBatch.objects.select_related("source")[:5],
        "recent_records": StagedRecord.objects.select_related("batch__source")[:8],
    }
    return render(request, "verification/dashboard.html", context)


@login_required
def record_list(request):
    records = StagedRecord.objects.select_related("batch__source", "verified_record")
    status = request.GET.get("status", "")
    record_type = request.GET.get("type", "")
    if status:
        records = records.filter(status=status)
    if record_type:
        records = records.filter(record_type=record_type)
    page = Paginator(records, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "verification/record_list.html",
        {
            "page": page,
            "selected_status": status,
            "selected_type": record_type,
            "record_types": StagedRecord.objects.values_list(
                "record_type", flat=True
            ).distinct(),
            "statuses": StagedRecord.Status.choices,
        },
    )


@login_required
@permission_required("verification.add_importbatch", raise_exception=True)
def import_data(request):
    form = ImportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        batch = import_records(
            source=form.cleaned_data["source"],
            reference=form.cleaned_data["reference"],
            record_type=form.cleaned_data["record_type"],
            rows=form.cleaned_data["data"],
            user=request.user,
        )
        messages.success(request, f"{batch.total_records} data berhasil ditampung.")
        return redirect("verification:records")
    return render(request, "verification/import.html", {"form": form})


@login_required
@permission_required("verification.change_verifiedrecord", raise_exception=True)
@require_http_methods(["GET", "POST"])
def verify_record(request, pk):
    staged = get_object_or_404(StagedRecord, pk=pk)
    verified = begin_verification(staged, request.user)
    form = VerificationForm(request.POST or None, instance=verified)
    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action", "save")
        save_verification(
            verified=verified,
            data=form.cleaned_data["verified_data_text"],
            notes=form.cleaned_data["verification_notes"],
            user=request.user,
            approve=action == "approve",
        )
        messages.success(
            request,
            "Data disetujui dan siap dipublikasikan."
            if action == "approve"
            else "Draf verifikasi tersimpan.",
        )
        return redirect("verification:records")
    return render(
        request,
        "verification/verify.html",
        {"staged": staged, "verified": verified, "form": form},
    )


def _api_error(message, status, *, authenticate=None):
    response = JsonResponse({"detail": message}, status=status)
    if authenticate:
        response["WWW-Authenticate"] = authenticate
    return response


def _authorize_api_request(request):
    authorization = request.headers.get("Authorization", "")
    scheme, separator, raw_token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not raw_token.strip():
        return None, _api_error(
            "Bearer token diperlukan.",
            401,
            authenticate='Bearer realm="datahub"',
        )
    try:
        claims = introspect_access_token(
            raw_token.strip(), required_scope=settings.DATAHUB_API_REQUIRED_SCOPE
        )
    except InvalidAccessToken as exc:
        return None, _api_error(
            str(exc),
            401,
            authenticate='Bearer realm="datahub", error="invalid_token"',
        )
    except InsufficientScope as exc:
        return None, _api_error(
            str(exc),
            403,
            authenticate=(
                'Bearer realm="datahub", error="insufficient_scope", '
                f'scope="{settings.DATAHUB_API_REQUIRED_SCOPE}"'
            ),
        )
    except (OAuthServerUnavailable, ImproperlyConfigured):
        return None, _api_error(
            "Validasi token sementara tidak tersedia.", 503
        )
    return claims, None


@login_required
def inpatient_indicators(request):
    records = InpatientIndicatorSource.objects.select_related("verification", "verification__verified_by")
    return render(request, "verification/indicator_list.html", {"records": records, "period_form": IndicatorPeriodForm()})


@login_required
@permission_required("verification.add_inpatientindicatorsource", raise_exception=True)
@require_http_methods(["POST"])
def sync_inpatient_indicators(request):
    form = IndicatorPeriodForm(request.POST)
    if form.is_valid():
        try:
            fetch_inpatient_indicator(period=form.cleaned_data["period"], user=request.user)
        except (
            ImproperlyConfigured,
            OAuthServerUnavailable,
            OSError,
            KeyError,
            ValueError,
        ) as exc:
            messages.error(request, f"Data belum dapat diambil: {exc}")
        else:
            messages.success(request, "Data indikator berhasil diambil dari SIMRS.")
    else:
        messages.error(request, "Silakan pilih bulan data yang benar.")
    return redirect("verification:indicators")


@login_required
@permission_required("verification.change_verifiedinpatientindicator", raise_exception=True)
@require_http_methods(["GET", "POST"])
def verify_inpatient_indicators(request, pk):
    source = get_object_or_404(InpatientIndicatorSource.objects.select_related("verification"), pk=pk)
    record = source.verification
    form = InpatientIndicatorVerificationForm(request.POST or None, instance=record)
    if request.method == "POST" and form.is_valid():
        approve = request.POST.get("action") == "approve"
        save_inpatient_verification(record=record, cleaned_data=form.cleaned_data, user=request.user, approve=approve)
        messages.success(request, "Data terverifikasi dan tersedia pada enam API." if approve else "Perubahan disimpan sebagai draf.")
        return redirect("verification:indicators")
    return render(request, "verification/indicator_verify.html", {"source": source, "record": record, "form": form})


INDICATOR_META = {
    "alos": ("Average Length of Stay", "hari"),
    "bor": ("Bed Occupancy Rate", "persen"),
    "bto": ("Bed Turn Over", "kali"),
    "toi": ("Turn Over Interval", "hari"),
    "gdr": ("Gross Death Rate", "per_1000"),
    "ndr": ("Net Death Rate", "per_1000"),
}


@require_http_methods(["GET"])
def indicator_api(request, indicator):
    if indicator not in INDICATOR_META:
        return _api_error("Indikator tidak ditemukan.", 404)
    _, auth_error = _authorize_api_request(request)
    if auth_error:
        return auth_error
    records = VerifiedInpatientIndicator.objects.filter(status=VerifiedInpatientIndicator.Status.APPROVED)
    if request.GET.get("tahun"):
        records = records.filter(period__year=request.GET["tahun"])
    if request.GET.get("bulan"):
        records = records.filter(period__month=request.GET["bulan"])
    name, unit = INDICATOR_META[indicator]
    return JsonResponse({"indikator": indicator.upper(), "nama": name, "satuan": unit, "count": records.count(), "results": [{"periode": item.period.strftime("%Y-%m"), "nilai": float(getattr(item, indicator)), "diverifikasi_pada": item.verified_at} for item in records]})


@require_http_methods(["GET"])
def public_records_api(request, record_type):
    _, auth_error = _authorize_api_request(request)
    if auth_error:
        return auth_error

    try:
        limit = min(max(int(request.GET.get("limit", 100)), 1), 500)
    except ValueError:
        return _api_error("Parameter limit harus berupa angka.", 400)
    records = VerifiedRecord.objects.filter(
        staged_record__record_type=record_type,
        status__in=(VerifiedRecord.Status.APPROVED, VerifiedRecord.Status.PUBLISHED),
    ).select_related("staged_record")[:limit]
    return JsonResponse(
        {
            "record_type": record_type,
            "count": len(records),
            "results": [
                {
                    "id": str(item.id),
                    "source_key": item.staged_record.source_key,
                    "data": item.verified_data,
                    "verified_at": item.approved_at,
                    "updated_at": item.updated_at,
                }
                for item in records
            ],
        }
    )
