from django.urls import path

from .views import ExternalHealthIndicatorList, ExternalIndicatorList, ExternalVerifiedRecordList


app_name = "api_external"

urlpatterns = [
    path("indicators/<slug:indicator>/", ExternalIndicatorList.as_view(), name="indicator"),
    path("records/<slug:record_type>/", ExternalVerifiedRecordList.as_view(), name="verified-records"),
    path("health-indicators/<slug:code>/", ExternalHealthIndicatorList.as_view(), name="health-indicator"),
]
