from django.apps import AppConfig


class SimrsMockConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "simrs_mock"
    verbose_name = "Mock API SIMRS"

    def ready(self):
        from . import schema  # noqa: F401
