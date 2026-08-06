from django.urls import path

from .views import DiseaseGroupView, TopDiseasesView, TouristVisitsView, VisitView


app_name = "simrs_mock"
urlpatterns = [
    path("visits/", VisitView.as_view(), name="visits"),
    path("top-diseases/", TopDiseasesView.as_view(), name="top-diseases"),
    path("tourist-visits/", TouristVisitsView.as_view(), name="tourist-visits"),
    path("disease-groups/", DiseaseGroupView.as_view(), name="disease-groups"),
]
