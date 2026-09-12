from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Cart, CartItem, Order, OrderItem, Purchase


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ("product", "title", "price")
    readonly_fields = fields
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "user", "total_display", "status", "created_at", "paid_at")
    list_filter = ("status", "created_at")
    search_fields = ("number", "user__mobile_number", "reference_id")
    date_hierarchy = "created_at"
    inlines = (OrderItemInline,)
    fields = (
        "number", "user", "status", "total", "created_at", "paid_at",
        "authority", "reference_id", "card_pan", "gateway_message",
    )
    readonly_fields = fields  # orders are records of money: never edited by hand

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description=_("مبلغ"), ordering="total")
    def total_display(self, obj):
        return "رایگان" if obj.is_free else f"{obj.total:,} تومان"


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    """Site admins can also grant a product by hand (e.g. support, or a gift)."""

    list_display = ("user", "product", "price_display", "order", "created_at")
    list_filter = ("product__primary_domain", "created_at")
    search_fields = ("user__mobile_number", "product__title")
    autocomplete_fields = ("user", "product")
    readonly_fields = ("created_at",)

    @admin.display(description=_("مبلغ"), ordering="price")
    def price_display(self, obj):
        return "رایگان" if not obj.price else f"{obj.price:,} تومان"


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    autocomplete_fields = ("product",)


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("__str__", "user", "count", "updated_at")
    search_fields = ("user__mobile_number",)
    inlines = (CartItemInline,)
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description=_("تعداد"))
    def count(self, obj):
        return obj.count