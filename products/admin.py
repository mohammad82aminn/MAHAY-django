from django import forms
from django.contrib import admin
from django.db.models import Prefetch
from django.utils.translation import gettext_lazy as _

from approvals.admin_base import ApprovalModelAdmin
from approvals.models import ChangeRequest

from .models import Product


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = "__all__"
        widgets = {"slug": forms.TextInput(attrs={"dir": "ltr"})}

    def clean(self):
        super().clean()
        primary, related = self.cleaned_data.get("primary_domain"), self.cleaned_data.get("related_domains")
        if primary and related and primary in related:
            self.add_error("related_domains", _("حوزه‌ی اصلی را در حوزه‌های مرتبط انتخاب نکنید."))
        return self.cleaned_data


@admin.register(Product)
class ProductAdmin(ApprovalModelAdmin):
    form = ProductAdminForm
    list_display = ("title", "product_type", "primary_domain", "price_display", "state")
    list_filter = ("product_type", "primary_domain", "is_published", "is_archived")
    search_fields = ("title", "slug")
    filter_horizontal = ("related_domains",)
    readonly_fields = ("created_by", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("product_type", "title", "slug", "summary", "description", "cover")}),
        (_("حوزه"), {"fields": ("primary_domain", "related_domains")}),
        (_("قیمت"), {"fields": ("price", "sale_price")}),
        (_("وضعیت"), {"fields": ("is_published", "is_archived", "created_by", "created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        pending = ChangeRequest.objects.filter(status=ChangeRequest.Status.PENDING)
        return (
            super().get_queryset(request)
            .select_related("primary_domain")
            .prefetch_related(Prefetch("change_requests", queryset=pending, to_attr="pending_requests"))
        )

    @admin.display(description=_("قیمت"))
    def price_display(self, obj):
        if obj.is_free:
            return "رایگان"
        if obj.sale_price is not None:
            return f"{obj.sale_price:,} تومان ({obj.discount_percent}٪ تخفیف)"
        return f"{obj.price:,} تومان"

    @admin.display(description=_("وضعیت"))
    def state(self, obj):
        waiting = {request.action for request in getattr(obj, "pending_requests", [])}
        if obj.is_archived:
            return "حذف‌شده از فروشگاه"
        if ChangeRequest.Action.ARCHIVE in waiting:
            return "منتشرشده (درخواست حذف در انتظار)"
        if obj.is_published:
            return "منتشرشده (تغییرات در انتظار)" if ChangeRequest.Action.UPDATE in waiting else "منتشرشده"
        return "در انتظار انتشار" if ChangeRequest.Action.CREATE in waiting else "پیش‌نویس"