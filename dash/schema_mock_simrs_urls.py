from django.urls import include, path


urlpatterns = [
    path("mock/simrs/v1/", include("simrs_mock.urls")),
]
