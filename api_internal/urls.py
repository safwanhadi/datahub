from django.urls import path

from .views import InternalIndicatorList, InternalMonthlyHealthList, InternalVerifiedRecordList


app_name = "api_internal"

urlpatterns = [
    path("indicators/inpatient/", InternalIndicatorList.as_view(), name="inpatient-indicators"),
    path("records/<slug:record_type>/", InternalVerifiedRecordList.as_view(), name="verified-records"),
    path("health-indicators/", InternalMonthlyHealthList.as_view(), name="health-indicators"),
]
