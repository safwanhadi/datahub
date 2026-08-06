from django.urls import include, path


urlpatterns = [
    path("api/external/v1/", include("api_external.urls")),
]
