from django.apps import AppConfig


class CommerceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "commerce"
    verbose_name = "فروش و سفارش‌ها"

    def ready(self):
        from . import signals  # noqa: F401  (connects the signal handlers)