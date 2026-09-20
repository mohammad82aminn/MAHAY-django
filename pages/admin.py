from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import ContactMessage, Page


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "show_in_footer", "order", "updated_at")
    list_editable = ("is_published", "show_in_footer", "order")
    search_fields = ("title", "body")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "name", "contact", "created_at", "is_handled")
    list_filter = ("is_handled", "created_at")
    search_fields = ("subject", "body", "name", "mobile_number", "email")
    list_editable = ("is_handled",)
    readonly_fields = ("name", "mobile_number", "email", "subject", "body", "created_at")
    fields = ("name", "mobile_number", "email", "subject", "body", "created_at", "is_handled")

    def has_add_permission(self, request):
        return False

    def pending_count(self, request):
        """Ticking «بررسی شد» is what clears the mark."""
        return self.get_queryset(request).filter(is_handled=False).count()

    @admin.display(description=_("راه تماس"))
    def contact(self, obj):
        return obj.mobile_number or obj.email or "—"