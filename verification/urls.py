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
    path("api/v1/indikator/<slug:indicator>/", views.indicator_api, name="indicator-api"),
    path("api/v1/data/<slug:record_type>/", views.public_records_api, name="public-api"),
]
