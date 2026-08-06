from django.urls import include, path


urlpatterns = [
    path("api/internal/v1/", include("api_internal.urls")),
]
