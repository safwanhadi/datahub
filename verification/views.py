import calendar
import json
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .forms import AdministrativeRegionForm, IndicatorPeriodForm, InpatientIndicatorStandardForm, InpatientIndicatorVerificationForm, InpatientWorkingDataCorrectionForm, MonthlyHealthVerificationForm, RegionAliasFormSet, SimrsApiEndpointForm
from .analytics import analyze_inpatient_record, get_applicable_standards
from .models import AdministrativeRegion, HealthIndicatorVerification, InpatientIndicatorSource, InpatientIndicatorStandard, MonthlyHealthIndicatorSource, SimrsApiEndpoint, VerifiedInpatientIndicator, VerifiedMonthlyHealthIndicator, VerifiedTouristVisitRow
from .health_metadata import HEALTH_INDICATORS, HEALTH_VERIFICATION_GROUPS
from .oauth import OAuthServerUnavailable
from .services import SimrsConnectionError, fetch_inpatient_indicator, fetch_monthly_health_indicators, reprocess_region_mappings, save_inpatient_verification, save_inpatient_working_data_correction, save_monthly_health_verification


@login_required
def api_documentation(request):
    absolute = lambda name: request.build_absolute_uri(reverse(name))
    external_base = request.build_absolute_uri("/api/external/v1/")
    internal_base = request.build_absolute_uri("/api/internal/v1/")
    external_endpoints = [
        ("Indikator rawat inap", external_base + "indicators/{indicator}/"),
        ("Indikator kesehatan", external_base + "health-indicators/{code}/"),
    ]
    internal_endpoints = [
        ("Indikator rawat inap dan rincian ruang", internal_base + "indicators/inpatient/"),
        ("Indikator kesehatan", internal_base + "health-indicators/"),
    ]
    return render(request, "verification/api_documentation.html", {
        "external_docs_url": absolute("external-docs"),
        "external_schema_url": absolute("external-schema"),
        "external_base_url": external_base,
        "external_endpoints": external_endpoints,
        "internal_docs_url": absolute("internal-docs"),
        "internal_schema_url": absolute("internal-schema"),
        "internal_base_url": internal_base,
        "internal_endpoints": internal_endpoints,
    })


@login_required
def dashboard(request):
    period_mode = request.GET.get("period", "monthly")
    if period_mode not in {"monthly", "quarterly", "semester", "yearly"}:
        period_mode = "monthly"

    latest_available_health = VerifiedMonthlyHealthIndicator.objects.filter(
        indicator_verifications__status=HealthIndicatorVerification.Status.APPROVED,
        source__period_type="month",
    ).select_related("source").distinct().first()
    default_reference = latest_available_health.source.period_start if latest_available_health else date.today().replace(day=1)
    try:
        reference = date.fromisoformat(f'{request.GET.get("reference", default_reference.strftime("%Y-%m"))}-01')
    except ValueError:
        reference = default_reference

    if period_mode == "quarterly":
        start_month = ((reference.month - 1) // 3) * 3 + 1
        period_start = date(reference.year, start_month, 1)
        period_end = date(reference.year, start_month + 2, calendar.monthrange(reference.year, start_month + 2)[1])
        period_label = f"Triwulan {(start_month - 1) // 3 + 1} {reference.year}"
    elif period_mode == "semester":
        start_month = 1 if reference.month <= 6 else 7
        end_month = start_month + 5
        period_start = date(reference.year, start_month, 1)
        period_end = date(reference.year, end_month, calendar.monthrange(reference.year, end_month)[1])
        period_label = f"Semester {1 if start_month == 1 else 2} {reference.year}"
    elif period_mode == "yearly":
        period_start, period_end = date(reference.year, 1, 1), date(reference.year, 12, 31)
        period_label = f"Tahun {reference.year}"
    else:
        period_start = reference.replace(day=1)
        period_end = date(reference.year, reference.month, calendar.monthrange(reference.year, reference.month)[1])
        period_label = period_start.strftime("%B %Y")

    approved_inpatient = VerifiedInpatientIndicator.objects.filter(
        status=VerifiedInpatientIndicator.Status.APPROVED,
        source__period_start__gte=period_start,
        source__period_start__lte=period_end,
    ).select_related("source", "verified_by")
    latest_inpatient = approved_inpatient.first()
    approved_health = VerifiedMonthlyHealthIndicator.objects.filter(
        indicator_verifications__status=HealthIndicatorVerification.Status.APPROVED,
        source__period_type="month",
        source__period_start__gte=period_start,
        source__period_start__lte=period_end,
    ).select_related("source", "verified_by").prefetch_related(
        "visit_rows", "top_disease_rows", "tourist_visit_rows", "disease_group_rows",
        "indicator_verifications",
    ).distinct()
    latest_health = approved_health.first()
    health_summary = None
    if latest_health:
        visits = []
        disease_totals = {}
        tourist_months = []
        month_cursor = period_start
        while month_cursor <= period_end:
            tourist_months.append({"period": month_cursor, "wisnus": 0, "wisman": 0, "total": 0})
            month_cursor = date(month_cursor.year + (month_cursor.month == 12), month_cursor.month % 12 + 1, 1)
        tourist_month_index = {(row["period"].year, row["period"].month): row for row in tourist_months}
        wisnus_total = wisman_total = 0
        for record in reversed(list(approved_health)):
            payload = record.to_payload()
            approved_codes = {
                item.indicator_code for item in record.indicator_verifications.all()
                if item.status == HealthIndicatorVerification.Status.APPROVED
            }
            approved_installations = {
                code.removesuffix("-visits") for code in approved_codes
                if code in {"outpatient-visits", "inpatient-visits", "emergency-visits"}
            }
            visits.extend(row for row in payload.get("visits", []) if row.get("installation") in approved_installations)
            for disease in payload.get("top_diseases", []) if "top-diseases" in approved_codes else []:
                key = (disease.get("installation"), disease.get("icd10_code"), disease.get("name"))
                disease_totals[key] = disease_totals.get(key, 0) + disease.get("patient_count", 0)
            tourist_rows = payload.get("tourist_visits", []) if "tourist-visits" in approved_codes else []
            month_wisnus = sum(row.get("count", 0) for row in tourist_rows if row.get("category") == "wisnus")
            month_wisman = sum(row.get("count", 0) for row in tourist_rows if row.get("category") == "wisman")
            wisnus_total += month_wisnus
            wisman_total += month_wisman
            month_row = tourist_month_index[(record.source.period_start.year, record.source.period_start.month)]
            month_row["wisnus"] += month_wisnus
            month_row["wisman"] += month_wisman
            month_row["total"] += month_wisnus + month_wisman
        top_diseases = [
            {"installation": key[0], "icd10_code": key[1], "name": key[2], "patient_count": count}
            for key, count in disease_totals.items()
        ]
        health_summary = {
            "record": latest_health,
            "total_visits": sum(row.get("count", 0) for row in visits),
            "outpatient": sum(row.get("count", 0) for row in visits if row.get("installation") == "outpatient"),
            "inpatient": sum(row.get("count", 0) for row in visits if row.get("installation") == "inpatient"),
            "emergency": sum(row.get("count", 0) for row in visits if row.get("installation") == "emergency"),
            "top_diseases": sorted(top_diseases, key=lambda row: row.get("patient_count", 0), reverse=True)[:5],
            "tourist_months": tourist_months,
            "wisnus_total": wisnus_total,
            "wisman_total": wisman_total,
            "tourist_published_total": wisnus_total + wisman_total,
        }
    indicator_analysis = analyze_inpatient_record(
        latest_inpatient, get_applicable_standards(latest_inpatient.period)
    ) if latest_inpatient else []
    context = {
        "inpatient_records": InpatientIndicatorSource.objects.select_related("verification")[:5],
        "health_records": MonthlyHealthIndicatorSource.objects.select_related("verification")[:5],
        "inpatient_total": InpatientIndicatorSource.objects.count(),
        "inpatient_approved": approved_inpatient.count(),
        "health_total": HealthIndicatorVerification.objects.count(),
        "health_approved": HealthIndicatorVerification.objects.filter(status=HealthIndicatorVerification.Status.APPROVED).count(),
        "latest_inpatient": latest_inpatient,
        "indicator_analysis": indicator_analysis,
        "indicator_ideal": sum(item["level"] == "ideal" for item in indicator_analysis),
        "indicator_attention": sum(item["level"] != "ideal" for item in indicator_analysis),
        "inpatient_trend": approved_inpatient[:6],
        "health_summary": health_summary,
        "period_mode": period_mode,
        "period_reference": reference.strftime("%Y-%m"),
        "period_start": period_start,
        "period_end": period_end,
        "period_label": period_label,
    }
    return render(request, "verification/dashboard.html", context)


def _is_datahub_admin(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name="Administrator DataHub").exists()
    )


datahub_admin_required = user_passes_test(_is_datahub_admin, login_url="login")


def _can_access_inpatient_workflow(user):
    # Daftar boleh dibaca semua pengguna login; aksi tetap dijaga permission
    # masing-masing view (sinkronisasi, koreksi, verifikasi, dan persetujuan).
    return user.is_authenticated


def _can_access_health_workflow(user):
    return user.is_authenticated


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


@permission_required("verification.view_administrativeregion", raise_exception=True)
def region_list(request):
    regions = AdministrativeRegion.objects.select_related("parent").prefetch_related("aliases")
    query = request.GET.get("q", "").strip()
    region_type = request.GET.get("type", "").strip()
    island_group = request.GET.get("group", "").strip()
    if query:
        regions = regions.filter(
            Q(official_code__icontains=query) | Q(name__icontains=query) | Q(aliases__alias__icontains=query)
        ).distinct()
    if region_type:
        regions = regions.filter(region_type=region_type)
    if island_group:
        regions = regions.filter(island_group__iexact=island_group)
    page = Paginator(regions, 50).get_page(request.GET.get("page"))
    unresolved = VerifiedTouristVisitRow.objects.filter(region__isnull=True).values(
        "origin_raw", "origin_code"
    ).annotate(total=Sum("count")).order_by("origin_raw")
    return render(request, "verification/region_list.html", {
        "regions": page, "unresolved": unresolved, "query": query,
        "selected_type": region_type, "selected_group": island_group,
        "region_types": AdministrativeRegion.RegionType.choices,
    })


@transaction.atomic
def region_edit(request, pk=None):
    required_permission = (
        "verification.change_administrativeregion"
        if pk
        else "verification.add_administrativeregion"
    )
    if not request.user.is_authenticated or not request.user.has_perm(required_permission):
        raise PermissionDenied
    region = get_object_or_404(AdministrativeRegion, pk=pk) if pk else AdministrativeRegion()
    form = AdministrativeRegionForm(request.POST or None, instance=region)
    formset = RegionAliasFormSet(request.POST or None, instance=region)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        region = form.save(commit=False)
        region.updated_by = request.user
        region.save()
        formset.instance = region
        aliases = formset.save()
        for alias in aliases:
            alias.updated_by = request.user
            alias.save()
            reprocess_region_mappings(alias.normalized_alias)
        reprocess_region_mappings(region.normalized_name)
        messages.success(request, "Master wilayah dan alias berhasil disimpan. Data yang cocok telah dinormalisasi ulang.")
        return redirect("verification:region-list")
    return render(request, "verification/region_form.html", {"form": form, "formset": formset, "region": region})


@permission_required("verification.view_simrsapiendpoint", raise_exception=True)
def simrs_endpoint_list(request):
    endpoints = list(SimrsApiEndpoint.objects.select_related("updated_by"))
    configured_codes = {endpoint.code for endpoint in endpoints}
    missing_endpoints = [
        {"code": code, "name": name}
        for code, name in SimrsApiEndpoint.Code.choices
        if code not in configured_codes
    ]
    return render(request, "verification/simrs_endpoint_list.html", {
        "endpoints": endpoints,
        "missing_endpoints": missing_endpoints,
    })


@transaction.atomic
def simrs_endpoint_edit(request, pk=None):
    required_permission = "verification.change_simrsapiendpoint" if pk else "verification.add_simrsapiendpoint"
    if not request.user.is_authenticated or not request.user.has_perm(required_permission):
        raise PermissionDenied
    endpoint = get_object_or_404(SimrsApiEndpoint, pk=pk) if pk else SimrsApiEndpoint()
    initial = {"code": request.GET.get("code", "")} if not pk else None
    form = SimrsApiEndpointForm(request.POST or None, instance=endpoint, initial=initial)
    if request.method == "POST" and form.is_valid():
        endpoint = form.save(commit=False)
        endpoint.updated_by = request.user
        endpoint.save()
        messages.success(request, "Konfigurasi API SIMRS berhasil disimpan dan langsung digunakan saat sinkronisasi berikutnya.")
        return redirect("verification:simrs-endpoint-list")
    return render(request, "verification/simrs_endpoint_form.html", {"form": form, "endpoint": endpoint})


@user_passes_test(_can_access_inpatient_workflow, login_url="login")
def inpatient_indicators(request):
    records = InpatientIndicatorSource.objects.select_related("verification", "verification__verified_by").prefetch_related("verification__room_indicators__source_room")
    return render(request, "verification/indicator_list.html", {"records": records, "period_form": IndicatorPeriodForm()})


@login_required
@permission_required("verification.change_verifiedinpatientindicator", raise_exception=True)
@require_http_methods(["GET", "POST"])
def correct_inpatient_working_data(request, pk):
    source = get_object_or_404(InpatientIndicatorSource.objects.select_related("verification"), pk=pk)
    record = source.verification
    initial = {
        "beds": record.working_beds,
        "care_days": record.working_care_days,
        "discharged_patients": record.working_discharged_patients,
        "deaths": record.working_deaths,
        "deaths_over_48h": record.working_deaths_over_48h,
        "days_in_period": record.working_days_in_period,
    }
    form = InpatientWorkingDataCorrectionForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        changed = save_inpatient_working_data_correction(
            record=record, cleaned_data=form.cleaned_data, user=request.user
        )
        messages.success(request, "Data kerja rawat inap diperbarui dan indikator dihitung ulang sebagai draf.") if changed else messages.info(request, "Tidak ada perubahan pada data kerja.")
        return redirect("verification:indicators")
    return render(request, "verification/inpatient_working_data_form.html", {
        "source": source, "record": record, "form": form,
    })


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
            SimrsConnectionError,
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
    source = get_object_or_404(InpatientIndicatorSource.objects.select_related("verification").prefetch_related("verification__room_indicators__source_room"), pk=pk)
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


@user_passes_test(_can_access_health_workflow, login_url="login")
def monthly_health_indicators(request):
    verifications = HealthIndicatorVerification.objects.select_related(
        "record__source", "verified_by"
    )
    queue = list(verifications.exclude(status=HealthIndicatorVerification.Status.APPROVED))
    approved = list(verifications.filter(status=HealthIndicatorVerification.Status.APPROVED))
    for item in queue + approved:
        item.indicator = HEALTH_VERIFICATION_GROUPS[item.indicator_code]
    return render(request, "verification/health_indicator_list.html", {
        "queue": queue,
        "approved": approved,
        "period_form": IndicatorPeriodForm(),
    })


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
def verify_monthly_health_indicators(request, pk, code):
    if code not in HEALTH_VERIFICATION_GROUPS:
        raise Http404("Indikator kesehatan tidak ditemukan.")
    source = get_object_or_404(MonthlyHealthIndicatorSource.objects.select_related("verification"), pk=pk)
    record = source.verification
    indicator_verification = get_object_or_404(
        record.indicator_verifications.select_related("verified_by"), indicator_code=code
    )
    form = MonthlyHealthVerificationForm(
        request.POST or None,
        payload=record.to_working_payload(),
        notes=indicator_verification.notes,
        indicator_code=code,
    )
    if request.method == "POST" and form.is_valid():
        approve = request.POST.get("action") == "approve"
        if approve and not request.user.has_perm("verification.approve_verifiedmonthlyhealthindicator"):
            messages.error(request, "Anda tidak memiliki izin untuk menyetujui indikator.")
            return redirect("verification:health-indicators")
        save_monthly_health_verification(record=record, indicator_verification=indicator_verification, data=form.cleaned_data["verified_data"], notes=form.cleaned_data["notes"], user=request.user, approve=approve)
        messages.success(request, "Data disetujui dan siap untuk API." if approve else "Perubahan disimpan sebagai draf.")
        return redirect("verification:health-indicators")
    return render(request, "verification/health_indicator_verify.html", {
        "source": source, "record": record, "verification": indicator_verification,
        "indicator_code": code, "indicator": HEALTH_VERIFICATION_GROUPS[code], "form": form,
    })
