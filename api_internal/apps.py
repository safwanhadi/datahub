from django.apps import AppConfig


class ApiInternalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api_internal"
    verbose_name = "API Internal"
