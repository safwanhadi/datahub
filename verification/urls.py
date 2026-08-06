from django.urls import path

from . import views

app_name = "verification"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("data/", views.record_list, name="records"),
    path("data/impor/", views.import_data, name="import"),
    path("data/<uuid:pk>/verifikasi/", views.verify_record, name="verify"),
    path("indikator-rawat-inap/", views.inpatient_indicators, name="indicators"),
    path("indikator-rawat-inap/ambil/", views.sync_inpatient_indicators, name="indicator-sync"),
    path("indikator-rawat-inap/<uuid:pk>/verifikasi/", views.verify_inpatient_indicators, name="indicator-verify"),
    path("indikator-kesehatan/", views.monthly_health_indicators, name="health-indicators"),
    path("indikator-kesehatan/ambil/", views.sync_monthly_health_indicators, name="health-indicator-sync"),
    path("indikator-kesehatan/<uuid:pk>/verifikasi/", views.verify_monthly_health_indicators, name="health-indicator-verify"),
]
