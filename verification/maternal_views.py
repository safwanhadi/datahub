from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from .forms import IndicatorPeriodForm
from .maternal import MaternalVerificationForm, fetch_maternal, save_maternal, summarize_maternal
from .models import MaternalPerinatalRecord
from .oauth import OAuthServerUnavailable
from .services import SimrsConnectionError


@login_required
def profile(request):
    today = timezone.localdate()
    form = IndicatorPeriodForm(request.GET or {"period_type": "year", "year": today.year})
    records = MaternalPerinatalRecord.objects.none()
    start = end = None
    if form.is_valid():
        start, end = form.cleaned_data["period_start"], form.cleaned_data["period_end"]
        records = MaternalPerinatalRecord.objects.filter(status="approved", period_start__gte=start, period_end__lte=end).order_by("period_start")
    records = list(records)
    summary = summarize_maternal(records)
    expected_months = ((end.year - start.year) * 12 + end.month - start.month + 1) if start else 0
    trend = [{"period": r.period_start, **{key: r.working_data["metrics"][key] for key in ("deliveries_total", "live_births", "maternal_deaths", "neonatal_deaths_early", "neonatal_deaths_late")}} for r in records]
    return render(request, "verification/maternal_profile.html", {
        "period_form": form, "fetch_form": IndicatorPeriodForm(initial={"period_type": "month", "year": today.year, "month": today.month}),
        "start": start, "end": end, "summary": summary, "trend": trend,
        "covered_months": len(records), "expected_months": expected_months,
        "queue": MaternalPerinatalRecord.objects.select_related("source", "verified_by").all(),
    })


@login_required
@permission_required("verification.add_monthlyhealthindicatorsource", raise_exception=True)
@require_POST
def sync(request):
    form = IndicatorPeriodForm(request.POST)
    if form.is_valid() and form.cleaned_data["period_type"] == "month":
        try:
            record = fetch_maternal(form.cleaned_data["period_start"], form.cleaned_data["period_end"], request.user)
        except (ImproperlyConfigured, OAuthServerUnavailable, SimrsConnectionError, ValidationError, OSError, ValueError) as exc:
            messages.error(request, f"Data maternal belum dapat diambil: {exc}")
        else:
            messages.success(request, "Snapshot tersimpan. Salinan verifikasi lama dipertahankan; gunakan muat ulang bila ingin memakai snapshot terbaru.")
            if request.user.has_perm("verification.change_verifiedmonthlyhealthindicator"):
                return redirect("verification:maternal-verify", pk=record.pk)
    else:
        messages.error(request, "Pilih satu bulan kalender penuh untuk pengambilan data maternal.")
    return redirect("verification:maternal-profile")


@login_required
@permission_required("verification.change_verifiedmonthlyhealthindicator", raise_exception=True)
@require_http_methods(["GET", "POST"])
def verify(request, pk):
    record = get_object_or_404(MaternalPerinatalRecord.objects.select_related("source"), pk=pk)
    form = MaternalVerificationForm(request.POST or None, record=record)
    if request.method == "POST":
        action = request.POST.get("action")
        if action not in {"reload", "save", "approve"}:
            form.add_error(None, "Tindakan tidak dikenali.")
        elif action == "approve" and not request.user.has_perm("verification.approve_verifiedmonthlyhealthindicator"):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        elif action == "reload" or form.is_valid():
            try:
                revision = int(request.POST.get("revision", ""))
                save_maternal(pk, revision, request.user, data=form.cleaned_data.get("payload") if action != "reload" else None,
                              notes=form.cleaned_data.get("notes", "") if action != "reload" else "",
                              approve=action == "approve", reload=action == "reload")
            except (ValidationError, ValueError) as exc:
                form.add_error(None, exc if isinstance(exc, ValidationError) else "Versi data tidak valid; buka ulang halaman.")
            else:
                messages.success(request, "Data disetujui untuk profil internal." if action == "approve" else "Salinan kerja tersimpan sebagai draf.")
                return redirect("verification:maternal-verify", pk=pk)
    return render(request, "verification/maternal_verify.html", {
        "record": record, "form": form,
        "source_json": __import__("json").dumps(record.source.payload, ensure_ascii=False, indent=2),
        "audits": record.audits.select_related("actor", "source").all(),
    })
