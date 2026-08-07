from django.urls import path

from .views import InternalIndicatorList, InternalMonthlyHealthList


app_name = "api_internal"

urlpatterns = [
    path("indicators/inpatient/", InternalIndicatorList.as_view(), name="inpatient-indicators"),
    path("health-indicators/", InternalMonthlyHealthList.as_view(), name="health-indicators"),
]
