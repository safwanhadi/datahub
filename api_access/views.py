from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ApiProductForm, ExternalApiClientForm, GrantFormSet
from .models import ApiAccessLog, ApiProduct, ExternalApiClient


def _is_datahub_admin(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name="Administrator DataHub").exists()
    )


datahub_admin_required = user_passes_test(_is_datahub_admin, login_url="login")


@datahub_admin_required
def access_overview(request):
    return render(request, "api_access/overview.html", {
        "clients": ExternalApiClient.objects.prefetch_related("grants__product"),
        "products": ApiProduct.objects.all(),
        "logs": ApiAccessLog.objects.all()[:30],
    })


@datahub_admin_required
@transaction.atomic
def client_edit(request, pk=None):
    client = get_object_or_404(ExternalApiClient, pk=pk) if pk else ExternalApiClient()
    form = ExternalApiClientForm(request.POST or None, instance=client)
    formset = GrantFormSet(request.POST or None, instance=client)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        client = form.save()
        formset.instance = client
        formset.save()
        messages.success(request, "Client API dan hak aksesnya berhasil disimpan.")
        return redirect("api_access:overview")
    return render(request, "api_access/client_form.html", {"form": form, "formset": formset, "client": client})


@datahub_admin_required
def product_edit(request, pk):
    product = get_object_or_404(ApiProduct, pk=pk)
    form = ApiProductForm(request.POST or None, instance=product)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Konfigurasi produk API berhasil disimpan.")
        return redirect("api_access:overview")
    return render(request, "api_access/product_form.html", {"form": form, "product": product})
