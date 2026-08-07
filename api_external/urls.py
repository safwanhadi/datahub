from django.urls import path

from .views import ExternalHealthIndicatorList, ExternalIndicatorList


app_name = "api_external"

urlpatterns = [
    path("indicators/<slug:indicator>/", ExternalIndicatorList.as_view(), name="indicator"),
    path("health-indicators/<slug:code>/", ExternalHealthIndicatorList.as_view(), name="health-indicator"),
]
