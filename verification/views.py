import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import IndicatorPeriodForm, InpatientIndicatorStandardForm, InpatientIndicatorVerificationForm, MonthlyHealthVerificationForm
from .analytics import analyze_inpatient_record, get_applicable_standards
from .models import InpatientIndicatorSource, InpatientIndicatorStandard, MonthlyHealthIndicatorSource, VerifiedInpatientIndicator, VerifiedMonthlyHealthIndicator
from .oauth import OAuthServerUnavailable
from .services import fetch_inpatient_indicator, fetch_monthly_health_indicators, save_inpatient_verification, save_monthly_health_verification


@login_required
def dashboard(request):
    approved_inpatient = VerifiedInpatientIndicator.objects.filter(
        status=VerifiedInpatientIndicator.Status.APPROVED
    ).select_related("source", "verified_by")
    latest_inpatient = approved_inpatient.first()
    approved_health = VerifiedMonthlyHealthIndicator.objects.filter(
        status=VerifiedMonthlyHealthIndicator.Status.APPROVED
    ).select_related("source", "verified_by").prefetch_related(
        "visit_rows", "top_disease_rows", "tourist_visit_rows", "disease_group_rows"
    )
    latest_health = approved_health.first()
    health_summary = None
    if latest_health:
        payload = latest_health.to_payload()
        visits = payload.get("visits", [])
        health_summary = {
            "record": latest_health,
            "total_visits": sum(row.get("count", 0) for row in visits),
            "outpatient": sum(row.get("count", 0) for row in visits if row.get("installation") == "outpatient"),
            "inpatient": sum(row.get("count", 0) for row in visits if row.get("installation") == "inpatient"),
            "emergency": sum(row.get("count", 0) for row in visits if row.get("installation") == "emergency"),
            "top_diseases": sorted(payload.get("top_diseases", []), key=lambda row: row.get("patient_count", 0), reverse=True)[:5],
        }
    indicator_analysis = analyze_inpatient_record(
        latest_inpatient, get_applicable_standards(latest_inpatient.period)
    ) if latest_inpatient else []
    context = {
        "inpatient_records": InpatientIndicatorSource.objects.select_related("verification")[:5],
        "health_records": MonthlyHealthIndicatorSource.objects.select_related("verification")[:5],
        "inpatient_total": InpatientIndicatorSource.objects.count(),
        "inpatient_approved": InpatientIndicatorSource.objects.filter(verification__status="approved").count(),
        "health_total": MonthlyHealthIndicatorSource.objects.count(),
        "health_approved": MonthlyHealthIndicatorSource.objects.filter(verification__status="approved").count(),
        "latest_inpatient": latest_inpatient,
        "indicator_analysis": indicator_analysis,
        "indicator_ideal": sum(item["level"] == "ideal" for item in indicator_analysis),
        "indicator_attention": sum(item["level"] != "ideal" for item in indicator_analysis),
        "inpatient_trend": approved_inpatient[:6],
        "health_summary": health_summary,
    }
    return render(request, "verification/dashboard.html", context)


def _is_datahub_admin(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name="Administrator DataHub").exists()
    )


datahub_admin_required = user_passes_test(_is_datahub_admin, login_url="login")


@datahub_admin_required
def indicator_standard_list(request):
    standards = InpatientIndicatorStandard.objects.select_related("updated_by")
    return render(request, "verification/standard_list.html", {"standards": standards})


@datahub_admin_required
@transaction.atomic
def indicator_standard_edit(request, pk=None):
    standard = get_object_or_404(InpatientIndicatorStandard, pk=pk) if pk else InpatientIndicatorStandard()
    form = InpatientIndicatorStandardForm(request.POST or None, instance=standard)
    if request.method == "POST" and form.is_valid():
        standard = form.save(commit=False)
        standard.updated_by = request.user
        standard.save()
        messages.success(request, "Standar indikator berhasil disimpan dan langsung digunakan sesuai masa berlakunya.")
        return redirect("verification:standard-list")
    return render(request, "verification/standard_form.html", {"form": form, "standard": standard})


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
