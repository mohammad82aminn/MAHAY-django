from django.contrib import admin
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from accounts.formatting import ltr
from accounts.roles import is_site_admin

from . import services
from .services import domain_managers
from .widgets import ExpertSelect
from .models import (
    ContactChannel, Referral, RequestEvent, RequestMessage, RequestPayment, ServiceRequest,
)


class ReferralInline(admin.TabularInline):
    """Site admins refer a request here; the expert's own fields are edited on the referral page."""

    model = Referral
    extra = 0
    fields = ("domain", "expert", "status", "quoted_price", "duration_text")
    show_change_link = True

    class Media:
        js = ("js/referral_expert.js",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "expert":
            # Autocomplete searched every registered user, customers included. The list is the
            # domain managers instead, and the row narrows it to the domain that was chosen.
            kwargs["queryset"] = domain_managers()
            kwargs["widget"] = ExpertSelect()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class PaymentInline(admin.TabularInline):
    model = RequestPayment
    extra = 0
    fields = ("amount", "method", "paid_at", "reference", "note")


class MessageInline(admin.TabularInline):
    """The file's conversation between site admins and the referred experts."""

    model = RequestMessage
    extra = 1
    fields = ("author", "body", "created_at")
    readonly_fields = ("author", "created_at")

    def has_change_permission(self, request, obj=None):
        return False  # messages are a record: written once, never edited


class EventInline(admin.TabularInline):
    model = RequestEvent
    extra = 0
    fields = ("text", "actor", "created_at")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ("tracking_code", "kind", "title", "domain_list", "status", "money", "created_at")
    list_filter = ("kind", "status", "level", "source", "domains", "created_at")
    search_fields = ("tracking_code", "title", "description", "name", "mobile_number")
    date_hierarchy = "created_at"
    filter_horizontal = ("domains",)
    inlines = (ReferralInline, PaymentInline, MessageInline, EventInline)
    readonly_fields = ("tracking_code", "user", "created_at", "updated_at", "money_summary", "attachment_link")
    fieldsets = (
        (None, {"fields": ("tracking_code", "kind", "status", "source", "created_at", "updated_at")}),
        (_("درخواست‌کننده"), {
            "fields": ("user", "name", "mobile_number", "email", "contact_channel", "contact_id"),
        }),
        (_("پروژه"), {
            "fields": ("title", "domains", "other_domain", "level", "need", "description",
                       "deadline", "attachment", "attachment_link"),
        }),
        (_("مالی"), {"fields": ("agreed_amount", "money_summary")}),
        (_("یادداشت"), {"fields": ("admin_note",)}),
    )

    # --- Access ---------------------------------------------------------------------

    def get_queryset(self, request):
        return services.visible_requests(request.user).prefetch_related("domains", "payments", "referrals")

    def pending_count(self, request):
        """Requests nobody has picked up yet. Moving one off «جدید» is what clears the mark."""
        return self.get_queryset(request).filter(status=ServiceRequest.Status.NEW).count()

    def has_add_permission(self, request):
        # Site admins may register a request that arrived on Telegram or by phone
        return is_site_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_site_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_site_admin(request.user)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if field is not None and db_field.name in ("mobile_number", "contact_id", "email"):
            field.widget.attrs["dir"] = "ltr"
        return field

    # --- Display --------------------------------------------------------------------

    @admin.display(description=_("حوزه‌ها"))
    def domain_list(self, obj):
        names = [str(domain) for domain in obj.domains.all()]
        if obj.other_domain:
            names.append(f"{obj.other_domain} (سایر)")
        return "، ".join(names) or "—"

    @admin.display(description=_("مالی"))
    def money(self, obj):
        if obj.agreed_amount is None:
            return obj.payment_state
        return f"{obj.paid_total:,} از {obj.agreed_amount:,} تومان"

    @admin.display(description=_("خلاصه‌ی مالی"))
    def money_summary(self, obj):
        if not obj.pk:
            return "—"
        rows = [
            ("جمع قیمت پیشنهادی کارشناسان", f"{obj.quoted_total:,} تومان"),
            ("مبلغ توافق‌شده", f"{obj.agreed_amount:,} تومان" if obj.agreed_amount else "تعیین نشده"),
            ("پرداخت‌شده", f"{obj.paid_total:,} تومان"),
            ("باقی‌مانده", f"{obj.remaining:,} تومان" if obj.remaining is not None else "—"),
            ("وضعیت", obj.payment_state),
        ]
        return format_html_join("", "<div><b>{}:</b> {}</div>", rows)

    @admin.display(description=_("دانلود ضمیمه"))
    def attachment_link(self, obj):
        if not obj.pk or not obj.attachment:
            return "—"
        from django.urls import reverse

        return format_html('<a href="{}">دانلود فایل</a>',
                           reverse("services:attachment", args=["request", obj.pk]))

    # --- Saving ---------------------------------------------------------------------

    def save_model(self, request, obj, form, change):
        old_status = ServiceRequest.objects.filter(pk=obj.pk).values_list("status", flat=True).first()
        super().save_model(request, obj, form, change)
        if not change:
            services.log(obj, request.user, f"درخواست توسط {request.user} ثبت شد (منبع: {obj.get_source_display()}).")
        elif old_status != obj.status:
            services.log(obj, request.user, f"وضعیت به «{obj.get_status_display()}» تغییر کرد.")

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, Referral) and instance.referred_by is None:
                instance.referred_by = request.user
            if isinstance(instance, RequestMessage) and instance.author is None:
                instance.author = request.user
            if isinstance(instance, RequestPayment) and instance.recorded_by is None:
                instance.recorded_by = request.user
            instance.save()

            if isinstance(instance, Referral):
                services.log(form.instance, request.user, f"ارجاع به حوزه‌ی {instance.domain}.")
            elif isinstance(instance, RequestPayment):
                services.log(form.instance, request.user, f"پرداخت {instance.amount:,} تومان ثبت شد.")
        for instance in formset.deleted_objects:
            instance.delete()
        formset.save_m2m()


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    """Where the domain's expert reports the price and the state of the work."""

    list_display = ("request", "domain", "expert", "status", "quoted_price", "updated_at")
    list_filter = ("status", "domain")
    search_fields = ("request__tracking_code", "request__title")
    readonly_fields = ("request", "domain", "referred_by", "created_at", "updated_at",
                       "request_summary", "attachment_link")
    fieldsets = (
        (None, {"fields": ("request", "request_summary", "domain", "expert", "status")}),
        (_("گزارش کارشناس"), {
            "fields": ("quoted_price", "duration_text", "feasibility", "done_work", "remaining_work",
                       "attachment", "attachment_link"),
        }),
        (_("اطلاعات ارجاع"), {"fields": ("referred_by", "created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return services.visible_referrals(request.user).select_related("request", "domain", "expert")

    def pending_count(self, request):
        """Work handed to a domain that its expert has not started on yet."""
        return self.get_queryset(request).filter(status=Referral.Status.REFERRED).count()

    def get_form(self, request, obj=None, **kwargs):
        request._referral = obj  # the domain is fixed here, so the expert list can follow it
        return super().get_form(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "expert":
            referral = getattr(request, "_referral", None)
            kwargs["queryset"] = domain_managers(referral.domain if referral else None)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_add_permission(self, request):
        return is_site_admin(request.user)  # referring is the site admin's job

    def has_delete_permission(self, request, obj=None):
        return is_site_admin(request.user)

    @admin.display(description=_("خلاصه‌ی درخواست"))
    def request_summary(self, obj):
        if not obj.pk:
            return "—"
        item = obj.request
        rows = [
            ("نوع", item.get_kind_display()),
            ("عنوان", item.title),
            ("سطح", item.get_level_display()),
            ("درخواست‌کننده", item.name),
            ("تماس", format_html("{} — {} {}", ltr(item.mobile_number),
                                 item.get_contact_channel_display(), ltr(item.contact_id))),
            ("توضیحات", item.description),
        ]
        return format_html_join("", "<div style='margin-bottom:.3rem'><b>{}:</b> {}</div>", rows)

    @admin.display(description=_("دانلود ضمیمه"))
    def attachment_link(self, obj):
        if not obj.pk or not obj.attachment:
            return "—"
        from django.urls import reverse

        return format_html('<a href="{}">دانلود فایل</a>',
                           reverse("services:attachment", args=["referral", obj.pk]))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        changed = "، ".join(form.changed_data) if change else ""
        services.log(obj.request, request.user,
                     f"گزارش حوزه‌ی {obj.domain} به‌روز شد ({changed})." if changed
                     else f"ارجاع به حوزه‌ی {obj.domain}.")


@admin.register(RequestMessage)
class RequestMessageAdmin(admin.ModelAdmin):
    """A manager can read and answer the messages of their own files here."""

    list_display = ("request", "author", "short_body", "created_at")
    search_fields = ("body", "request__tracking_code")
    readonly_fields = ("author", "created_at")
    fields = ("request", "author", "body", "created_at")

    def get_queryset(self, request):
        return RequestMessage.objects.filter(
            request__in=services.visible_requests(request.user)
        ).select_related("request", "author")

    def has_change_permission(self, request, obj=None):
        return False  # written once

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "request":
            kwargs["queryset"] = services.visible_requests(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        obj.author = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description=_("پیام"))
    def short_body(self, obj):
        return obj.body[:80]


@admin.register(RequestPayment)
class RequestPaymentAdmin(admin.ModelAdmin):
    list_display = ("request", "amount", "method", "paid_at", "recorded_by")
    list_filter = ("method", "paid_at")
    search_fields = ("request__tracking_code", "reference")
    readonly_fields = ("recorded_by",)

    def has_module_permission(self, request):
        return is_site_admin(request.user)

    def save_model(self, request, obj, form, change):
        if obj.recorded_by is None:
            obj.recorded_by = request.user
        super().save_model(request, obj, form, change)
        services.log(obj.request, request.user, f"پرداخت {obj.amount:,} تومان ثبت شد.")


@admin.register(ContactChannel)
class ContactChannelAdmin(admin.ModelAdmin):
    list_display = ("kind", "label", "value", "is_active", "order")
    list_editable = ("is_active", "order")