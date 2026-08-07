from django.urls import path

from . import views

app_name = "api_access"

urlpatterns = [
    path("", views.access_overview, name="overview"),
    path("clients/new/", views.client_edit, name="client-create"),
    path("clients/<int:pk>/", views.client_edit, name="client-edit"),
    path("products/<int:pk>/", views.product_edit, name="product-edit"),
]
