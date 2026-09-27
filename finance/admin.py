"""
The finance pages. Only the finance managers and the site admins see any of it; the rest of the
staff reach their own figures through «صورت‌حساب من» (see finance.reports).
"""
import csv

from django import forms
from django.contrib import admin, messages
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from accounts.formatting import ltr
from accounts.models import User
from accounts.roles import can_see_finance
from domains.access import managed_domains

from . import balances, shares
from .models import (
    DomainShareRule, FinanceReport, MyStatement, Payout, ProductShareRule, Receipt, RequestShareRule, Share,
)

STATEMENT_ROWS = 100


class FinanceOnly:
    """Nothing here for anyone but the finance managers and the site admins, whatever their permissions."""

    def has_module_permission(self, request):
        return can_see_finance(request.user)

    def has_view_permission(self, request, obj=None):
        return can_see_finance(request.user)

    def has_add_permission(self, request):
        return can_see_finance(request.user) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return can_see_finance(request.user) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return can_see_finance(request.user) and super().has_delete_permission(request, obj)


# --- The ledger ---------------------------------------------------------------------

class ShareInline(admin.TabularInline):
    model = Share
    extra = 0
    can_delete = False
    fields = ("role", "person", "domain", "percent", "amount_toman")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description=_("مبلغ"))
    def amount_toman(self, obj):
        return f"{obj.amount:,} تومان"


class ReviewedFilter(admin.SimpleListFilter):
    title = _("بررسی")
    parameter_name = "reviewed"

    def lookups(self, request, model_admin):
        return (("no", _("بررسی‌نشده")), ("yes", _("بررسی‌شده")))

    def queryset(self, request, queryset):
        if self.value() == "no":
            return queryset.filter(reviewed_at__isnull=True, voided_at__isnull=True)
        if self.value() == "yes":
            return queryset.filter(reviewed_at__isnull=False)
        return queryset


class SplitFilter(admin.SimpleListFilter):
    title = _("سهم‌بندی")
    parameter_name = "split"

    def lookups(self, request, model_admin):
        return (("done", _("سهم‌بندی‌شده")), ("waiting", _("سهم‌بندی‌نشده")), ("void", _("باطل‌شده")))

    def queryset(self, request, queryset):
        if self.value() == "done":
            return queryset.filter(split_at__isnull=False, voided_at__isnull=True)
        if self.value() == "waiting":
            return queryset.filter(split_at__isnull=True, voided_at__isnull=True)
        if self.value() == "void":
            return queryset.filter(voided_at__isnull=False)
        return queryset


@admin.register(Receipt)
class ReceiptAdmin(FinanceOnly, admin.ModelAdmin):
    list_display = ("received_at", "title", "payer", "amount_toman", "method", "split_state", "reviewed")
    list_filter = (ReviewedFilter, SplitFilter, "source", "method", "received_at")
    search_fields = ("title", "payer_name", "payer_mobile", "reference")
    date_hierarchy = "received_at"
    inlines = (ShareInline,)
    actions = ("mark_reviewed", "split_again", "export_csv")
    fieldsets = (
        (None, {"fields": ("title", "source_link", "source", "amount_toman", "method", "received_at", "reference", "card_pan")}),
        (_("پرداخت‌کننده"), {"fields": ("payer", "payer_name", "payer_mobile_ltr")}),
        (_("وضعیت"), {"fields": ("split_state", "split_at", "unsplit_reason", "reviewed_at", "reviewed_by",
                                 "voided_at", "void_reason")}),
    )
    readonly_fields = (
        "title", "source_link", "source", "amount_toman", "method", "received_at", "reference", "card_pan",
        "payer", "payer_name", "payer_mobile_ltr", "split_state", "split_at", "unsplit_reason",
        "reviewed_at", "reviewed_by", "voided_at", "void_reason",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("reviewed_by")

    def pending_count(self, request):
        """Money that came in and nobody in finance has looked at yet."""
        if not can_see_finance(request.user):
            return 0
        return Receipt.objects.filter(reviewed_at__isnull=True, voided_at__isnull=True).count()

    # A receipt is a record of money that arrived: made by the system, never typed or removed here
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description=_("بابت چه"))
    def source_link(self, obj):
        """The course or the order it paid for — the page opens only for someone allowed to see it."""
        if obj.product_id:
            return format_html('<a href="{}">{}</a>', obj.product.get_absolute_url(), obj.product)
        if obj.service_request_id:
            return str(obj.service_request)
        return "—"

    @admin.display(description=_("پرداخت‌کننده"), ordering="payer_name")
    def payer(self, obj):
        return obj.payer_name or ltr(obj.payer_mobile) or "—"

    @admin.display(description=_("موبایل پرداخت‌کننده"))
    def payer_mobile_ltr(self, obj):
        return ltr(obj.payer_mobile) if obj.payer_mobile else "—"

    @admin.display(description=_("مبلغ"), ordering="amount")
    def amount_toman(self, obj):
        return f"{obj.amount:,} تومان"

    @admin.display(description=_("سهم‌بندی"))
    def split_state(self, obj):
        if obj.is_void:
            return "باطل‌شده"
        return "سهم‌بندی‌شده" if obj.split_at else "سهم‌بندی‌نشده"

    @admin.display(description=_("بررسی"), boolean=True)
    def reviewed(self, obj):
        return obj.reviewed_at is not None

    @admin.action(description=_("علامت «بررسی شد»"))
    def mark_reviewed(self, request, queryset):
        done = queryset.filter(reviewed_at__isnull=True).update(reviewed_at=timezone.now(), reviewed_by=request.user)
        self.message_user(request, f"{done} دریافت بررسی‌شده علامت خورد.")

    @admin.action(description=_("سهم‌بندی دوباره با درصدهای فعلی"))
    def split_again(self, request, queryset):
        results = [shares.split(receipt) for receipt in queryset.filter(voided_at__isnull=True)]
        done, left = results.count(True), results.count(False)
        self.message_user(request, f"{done} دریافت سهم‌بندی شد."
                          + (f" {left} دریافت هنوز قابل سهم‌بندی نیست؛ دلیلش در ستون جزئیات هر کدام آمده است." if left else ""),
                          messages.SUCCESS if not left else messages.WARNING)

    @admin.action(description=_("خروجی Excel (CSV)"))
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="receipts.csv"'
        response.write("﻿")  # so Excel reads the Persian text as UTF-8
        writer = csv.writer(response)
        writer.writerow(["زمان دریافت", "بابت", "منشأ", "پرداخت‌کننده", "موبایل", "مبلغ (تومان)", "روش",
                         "شماره پیگیری", "سهم‌بندی", "بررسی‌شده"])
        for receipt in queryset.order_by("received_at"):
            writer.writerow([
                timezone.localtime(receipt.received_at).strftime("%Y-%m-%d %H:%M"), receipt.title,
                receipt.get_source_display(), receipt.payer_name, receipt.payer_mobile, receipt.amount,
                receipt.get_method_display(), receipt.reference, self.split_state(receipt),
                "بله" if receipt.reviewed_at else "خیر",
            ])
        return response


# --- Percentages --------------------------------------------------------------------

@admin.register(DomainShareRule)
class DomainShareRuleAdmin(FinanceOnly, admin.ModelAdmin):
    """One row per domain, made with the domain; the percentages are filled in right in the list."""

    list_display = ("domain", "sale_instructor", "sale_manager", "sale_fund",
                    "service_expert", "service_manager", "service_fund")
    list_editable = list_display[1:]
    fieldsets = (
        (None, {"fields": ("domain",)}),
        (_("فروش دوره یا پروژه‌ی آماده"), {
            "fields": ("sale_instructor", "sale_manager", "sale_fund"),
            "description": _("باقی‌مانده‌ی هر فروش سهم مجموعه است. تا همه‌ی درصدها پر نشده، فروش‌ها سهم‌بندی نمی‌شوند."),
        }),
        (_("سفارش پروژه یا مشاوره"), {
            "fields": ("service_expert", "service_manager", "service_fund"),
            "description": _("باقی‌مانده‌ی هر پرداخت سهم مجموعه است."),
        }),
    )
    readonly_fields = ("domain",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("domain")

    def has_add_permission(self, request):
        return False  # made automatically with each domain

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductShareRule)
class ProductShareRuleAdmin(FinanceOnly, admin.ModelAdmin):
    list_display = ("product", "instructor", "manager", "fund")
    search_fields = ("product__title",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("product")


@admin.register(RequestShareRule)
class RequestShareRuleAdmin(FinanceOnly, admin.ModelAdmin):
    list_display = ("request", "expert", "manager", "fund")
    search_fields = ("request__tracking_code", "request__title")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("request")


# --- Payouts ------------------------------------------------------------------------

class PayoutForm(forms.ModelForm):
    class Meta:
        model = Payout
        fields = ("person", "fund", "amount", "paid_on", "reference", "note")
        widgets = {"reference": forms.TextInput(attrs={"dir": "ltr"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only people who work here are ever paid a share; the customer list stays closed
        self.fields["person"].queryset = User.objects.filter(is_staff=True).order_by("first_name", "last_name")


@admin.register(Payout)
class PayoutAdmin(FinanceOnly, admin.ModelAdmin):
    form = PayoutForm
    list_display = ("paid_on", "recipient", "amount_toman", "reference", "recorded_by")
    list_filter = ("paid_on", "fund")
    search_fields = ("reference", "note", "person__first_name", "person__last_name", "person__mobile_number")
    date_hierarchy = "paid_on"
    readonly_fields = ("recorded_by", "created_at")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("person", "fund", "recorded_by")

    def save_model(self, request, obj, form, change):
        if obj.recorded_by_id is None:
            obj.recorded_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description=_("به"))
    def recipient(self, obj):
        return obj.person or f"صندوق حوزه‌ی {obj.fund}"

    @admin.display(description=_("مبلغ"), ordering="amount")
    def amount_toman(self, obj):
        return f"{obj.amount:,} تومان"


# --- Reports ------------------------------------------------------------------------

def csv_response(name, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}.csv"'
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


@admin.register(FinanceReport)
class FinanceReportAdmin(FinanceOnly, admin.ModelAdmin):
    """Income over a period, and what everyone and every fund is still owed."""

    def get_urls(self):
        return [path("", self.admin_site.admin_view(self.report_view), name="finance_financereport_changelist")]

    def report_view(self, request):
        if not can_see_finance(request.user):
            raise Http404
        period = request.GET.get("period")
        if period not in balances.PERIODS:
            period = balances.DEFAULT_PERIOD
        people, funds = balances.people(), balances.funds()
        export = request.GET.get("export")
        if export == "people":
            return csv_response("balances", ["نام", "موبایل", "سهم کل", "تسویه‌شده", "مانده"], [
                (row["person"].get_full_name(), row["person"].mobile_number, row["earned"], row["paid"], row["owed"])
                for row in people
            ])
        if export == "funds":
            return csv_response("funds", ["حوزه", "سهم کل", "برداشت‌شده", "مانده"], [
                (row["domain"].name, row["earned"], row["paid"], row["owed"]) for row in funds
            ])
        return render(request, "admin/finance/report.html", {
            **self.admin_site.each_context(request),
            "title": _("گزارش‌های مالی"), "opts": self.model._meta,
            "period": period,
            "periods": [(key, label) for key, (_days, label) in balances.PERIODS.items()],
            "income": balances.income(period),
            "people": people, "funds": funds,
        })

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MyStatement)
class MyStatementAdmin(admin.ModelAdmin):
    """
    Every staff member's own figures, and nobody else's: the shares they were given, what was paid
    to them, and what is still owed. A domain manager also sees their domains' funds.
    """

    def get_urls(self):
        return [path("", self.admin_site.admin_view(self.statement_view), name="finance_mystatement_changelist")]

    def statement_view(self, request):
        user = request.user
        mine = balances.people(person_ids=[user.pk])
        managed = list(managed_domains(user).values_list("pk", flat=True))
        return render(request, "admin/finance/statement.html", {
            **self.admin_site.each_context(request),
            "title": _("صورت‌حساب من"), "opts": self.model._meta,
            "totals": mine[0] if mine else {"earned": 0, "paid": 0, "owed": 0},
            "shares": (
                Share.objects.filter(person=user, receipt__voided_at__isnull=True)
                .select_related("receipt", "domain").order_by("-receipt__received_at")[:STATEMENT_ROWS]
            ),
            "payouts": Payout.objects.filter(person=user)[:STATEMENT_ROWS],
            "funds": balances.funds(domain_ids=managed) if managed else [],
        })

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_staff

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
