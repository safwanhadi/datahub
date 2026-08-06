import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Count
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import ImportForm, IndicatorPeriodForm, InpatientIndicatorVerificationForm, MonthlyHealthVerificationForm, VerificationForm
from .models import ImportBatch, InpatientIndicatorSource, MonthlyHealthIndicatorSource, StagedRecord, VerifiedInpatientIndicator, VerifiedRecord
from .oauth import OAuthServerUnavailable
from .services import begin_verification, fetch_inpatient_indicator, fetch_monthly_health_indicators, import_records, save_inpatient_verification, save_monthly_health_verification, save_verification


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
        approve = action == "approve"
        if approve and not request.user.has_perm("verification.approve_verifiedrecord"):
            messages.error(request, "Anda tidak memiliki izin untuk menyetujui data.")
            return redirect("verification:records")
        save_verification(
            verified=verified,
            data=form.cleaned_data["verified_data_text"],
            notes=form.cleaned_data["verification_notes"],
            user=request.user,
            approve=approve,
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
            fetch_inpatient_indicator(period_start=form.cleaned_data["period_start"], period_end=form.cleaned_data["period_end"], period_type=form.cleaned_data["period_type"], user=request.user)
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
        if approve and not request.user.has_perm("verification.approve_verifiedinpatientindicator"):
            messages.error(request, "Anda tidak memiliki izin untuk menyetujui indikator.")
            return redirect("verification:indicators")
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


@login_required
def monthly_health_indicators(request):
    records = MonthlyHealthIndicatorSource.objects.select_related("verification", "verification__verified_by")
    return render(request, "verification/health_indicator_list.html", {"records": records, "period_form": IndicatorPeriodForm()})


@login_required
@permission_required("verification.add_monthlyhealthindicatorsource", raise_exception=True)
@require_http_methods(["POST"])
def sync_monthly_health_indicators(request):
    form = IndicatorPeriodForm(request.POST)
    if form.is_valid():
        try:
            fetch_monthly_health_indicators(period_start=form.cleaned_data["period_start"], period_end=form.cleaned_data["period_end"], period_type=form.cleaned_data["period_type"], user=request.user)
        except (ImproperlyConfigured, OAuthServerUnavailable, ValidationError, OSError, KeyError, ValueError) as exc:
            messages.error(request, f"Data belum dapat diambil: {exc}")
        else:
            messages.success(request, "Indikator kesehatan berhasil diambil dari SIMRS.")
    else:
        messages.error(request, "Silakan pilih bulan data yang benar.")
    return redirect("verification:health-indicators")


@login_required
@permission_required("verification.change_verifiedmonthlyhealthindicator", raise_exception=True)
@require_http_methods(["GET", "POST"])
def verify_monthly_health_indicators(request, pk):
    source = get_object_or_404(MonthlyHealthIndicatorSource.objects.select_related("verification"), pk=pk)
    record = source.verification
    form = MonthlyHealthVerificationForm(
        request.POST or None,
        payload=record.to_payload(),
        notes=record.notes,
    )
    if request.method == "POST" and form.is_valid():
        approve = request.POST.get("action") == "approve"
        if approve and not request.user.has_perm("verification.approve_verifiedmonthlyhealthindicator"):
            messages.error(request, "Anda tidak memiliki izin untuk menyetujui indikator.")
            return redirect("verification:health-indicators")
        save_monthly_health_verification(record=record, data=form.cleaned_data["verified_data"], notes=form.cleaned_data["notes"], user=request.user, approve=approve)
        messages.success(request, "Data disetujui dan siap untuk API." if approve else "Perubahan disimpan sebagai draf.")
        return redirect("verification:health-indicators")
    return render(request, "verification/health_indicator_verify.html", {"source": source, "record": record, "form": form})
