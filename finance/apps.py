from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "finance"
    verbose_name = "امور مالی"

    def ready(self):
        from . import signals  # noqa: F401  (connects the signal handlers)
