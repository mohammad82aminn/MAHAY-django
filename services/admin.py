from django import forms
from django.contrib import admin
from django.contrib.auth.models import Group
from django.db.models import Exists, OuterRef, Prefetch, Q
from django.http import Http404
from django.shortcuts import render
from django.urls import path
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from accounts.formatting import ltr
from accounts.roles import is_site_admin
from domains.access import has_managers, is_manager, managed_domains

from . import heard_from_report, services
from .services import domain_people
from .widgets import ExpertSelect
from .models import (
    ContactChannel, HeardFromReport, Referral, RequestEvent, RequestMessage, RequestPayment, ServiceRequest,
)


class ReferralInlineForm(forms.ModelForm):
    class Meta:
        model = Referral
        fields = "__all__"

    def clean(self):
        data = super().clean()
        domain, expert = data.get("domain"), data.get("expert")
        if expert and "expert" in self.changed_data and domain is not None and has_managers(domain):
            # The site admin chooses the domain; who inside it does the work is its managers' call
            self.add_error("expert", _("این حوزه مدیر دارد و انتخاب کارشناس با مدیر حوزه است؛ فقط حوزه را انتخاب کنید."))
        return data


class ReferralInline(admin.TabularInline):
    """
    Site admins refer a request here by choosing the domain; its managers then pick the expert
    (a site admin picks one only for a domain with no manager). The expert's own fields are edited
    on the referral page.
    """

    model = Referral
    form = ReferralInlineForm

    def get_queryset(self, request):
        # Another domain's price on the same request is none of an expert's business
        return super().get_queryset(request).filter(pk__in=services.visible_referrals(request.user).values("pk"))
    extra = 0
    fields = ("domain", "expert", "expert_handle", "status", "quoted_price", "duration_text")
    readonly_fields = ("expert_handle",)
    show_change_link = True

    @admin.display(description=_("آیدی کارشناس"))
    def expert_handle(self, obj):
        # Shown so the admin can pass it to the customer without hunting through user accounts
        if obj.expert_id and obj.expert.contact_handle:
            return ltr(obj.expert.contact_handle)
        return "—"

    class Media:
        js = ("js/referral_expert.js",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "expert":
            # Autocomplete searched every registered user, customers included. The list is the
            # domain managers instead, and the row narrows it to the domain that was chosen.
            kwargs["queryset"] = domain_people()
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
    list_display = ("tracking_code", "kind", "title", "stage", "domain_list", "money", "created_at")
    list_filter = ("kind", "status", "level", "source", "domains", "created_at")
    search_fields = ("tracking_code", "title", "description", "name", "mobile_number")
    date_hierarchy = "created_at"
    filter_horizontal = ("domains",)
    inlines = (ReferralInline, PaymentInline, MessageInline, EventInline)
    readonly_fields = ("tracking_code", "user", "created_at", "updated_at", "money_summary",
                       "attachment_link", "stage_note")
    fieldsets = (
        (None, {"fields": ("stage_note", "tracking_code", "kind", "status", "source",
                           "created_at", "updated_at")}),
        (_("درخواست‌کننده"), {
            "fields": ("user", "name", "mobile_number", "email", "contact_channel", "contact_id",
                       "heard_from", "heard_from_other"),
        }),
        (_("پروژه"), {
            "fields": ("title", "domains", "other_domain", "level", "need", "description",
                       "deadline", "minutes", "attachment", "attachment_link"),
        }),
        (_("مالی"), {"fields": ("agreed_amount", "prepay_override", "money_summary")}),
        (_("یادداشت"), {"fields": ("admin_note",)}),
    )

    # --- Access ---------------------------------------------------------------------

    def get_fieldsets(self, request, obj=None):
        if is_site_admin(request.user):
            return self.fieldsets
        # An expert is here to read the brief, not to audit the file: the source it arrived by,
        # how the person heard of us, the money and the admin's private note are none of their business.
        return (
            (None, {"fields": ("stage_note", "tracking_code", "kind", "status")}),
            (_("درخواست‌کننده"), {"fields": ("name", "mobile_number", "contact_channel", "contact_id")}),
            (_("پروژه"), {
                "fields": ("title", "domains", "other_domain", "level", "need", "description",
                           "deadline", "minutes", "attachment_link"),
            }),
        )

    def get_list_display(self, request):
        if is_site_admin(request.user):
            return self.list_display
        return [column for column in self.list_display if column != "money"]  # the money is the admins' side

    def get_inlines(self, request, obj):
        if is_site_admin(request.user):
            return self.inlines
        return (ReferralInline, MessageInline)  # no payments, no full history

    def get_queryset(self, request):
        # Whether each referral's domain has a manager is read once for the whole page, for the stage column
        has_managers_now = Exists(Group.objects.filter(managers_domain=OuterRef("domain"), user__is_active=True))
        referrals = Referral.objects.annotate(domain_has_managers=has_managers_now)
        return services.visible_requests(request.user).prefetch_related(
            "domains", "payments", Prefetch("referrals", queryset=referrals),
        )

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

    @admin.display(description=_("مرحله"))
    def stage(self, obj):
        _key, label, turn = services.stage_of(obj)
        return f"{label} — نوبت {turn}" if turn != "—" else label

    @admin.display(description=_("الان چه باید بشود"))
    def stage_note(self, obj):
        if not obj.pk:
            return "—"
        _key, label, turn = services.stage_of(obj)
        if turn == "—":
            return format_html("<b>{}</b>", label)
        return format_html("<b>{}</b> — نوبت <b>{}</b> است.", label, turn)

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

    @admin.display(description=_("وضعیت قیمت"))
    def quote_state(self, obj):
        if obj.quoted_price is None:
            return "—"
        if obj.quote_approved_at is None:
            return "منتظر تأیید مدیر حوزه"
        who = obj.quote_approved_by.get_full_name() if obj.quote_approved_by else ""
        return f"تأیید شده{f' توسط {who}' if who else ''}"

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
            changed = next((f.changed_data for f in formset.forms if f.instance is instance), [])
            if isinstance(instance, Referral) and "quoted_price" in changed and instance.quoted_price is not None:
                services.price_set(instance, request.user)
            instance.save()

            if isinstance(instance, Referral):
                services.log(form.instance, request.user, f"ارجاع به حوزه‌ی {instance.domain}.")
                services.mark_referred(form.instance, request.user)
                if "expert" in changed and instance.expert is not None:
                    services.assign(instance, instance.expert, request.user)
            elif isinstance(instance, RequestPayment):
                services.log(form.instance, request.user, f"پرداخت {instance.amount:,} تومان ثبت شد.")
        for instance in formset.deleted_objects:
            instance.delete()
        formset.save_m2m()


class ReferralForm(forms.ModelForm):
    approve_quote = forms.BooleanField(
        label=_("تأیید قیمت کارشناس"), required=False,
        help_text=_("با تأیید، قیمت برای مدیر کل فرستاده می‌شود تا مبلغ نهایی را تعیین کند."),
    )

    class Meta:
        model = Referral
        fields = "__all__"


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    """
    Where a domain works on its share of a request: its managers pick the expert and agree to
    the price, the expert reports the price and the state of the work.
    """

    form = ReferralForm

    list_display = ("request", "domain", "expert", "status", "quoted_price", "updated_at")
    list_filter = ("status", "domain")
    search_fields = ("request__tracking_code", "request__title")
    readonly_fields = ("request", "domain", "referred_by", "created_at", "updated_at",
                       "request_summary", "attachment_link", "quote_state")

    def get_fieldsets(self, request, obj=None):
        price = ["quoted_price", "quote_state"]
        if obj is not None and self._may_approve_price(request, obj):
            price.append("approve_quote")
        return (
            (None, {"fields": ("request", "request_summary", "domain", "expert", "introduced_at", "status")}),
            (_("گزارش کارشناس"), {
                "fields": (*price, "duration_text", "feasibility", "done_work", "remaining_work",
                           "attachment", "attachment_link"),
            }),
            (_("اطلاعات ارجاع"), {"fields": ("referred_by", "created_at", "updated_at")}),
        )

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj is not None and not services.may_assign(request.user, obj):
            fields = (*fields, "expert")  # an expert doesn't hand their work on
        return fields

    @staticmethod
    def _may_approve_price(request, obj):
        return (obj.quoted_price is not None and obj.quote_approved_at is None
                and is_manager(request.user, obj.domain))

    def get_queryset(self, request):
        return services.visible_referrals(request.user).select_related("request", "domain", "expert")

    def pending_count(self, request):
        """
        What waits on the visitor: for a domain manager, work still without an expert and prices
        to agree to; for an expert, work handed to them not yet started; for a site admin, work in
        a domain with no manager that still needs an expert.
        """
        if is_site_admin(request.user):
            has_managers_now = Exists(Group.objects.filter(managers_domain=OuterRef("domain"), user__is_active=True))
            return Referral.objects.filter(~has_managers_now, expert__isnull=True).count()
        mine = managed_domains(request.user)
        waiting = (
            Q(domain__in=mine, expert__isnull=True)
            | Q(domain__in=mine, quoted_price__isnull=False, quote_approved_at__isnull=True)
            | Q(expert=request.user, status=Referral.Status.REFERRED)
        )
        return self.get_queryset(request).filter(waiting).count()

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request, obj):
            return False
        if obj is None or is_site_admin(request.user) or is_manager(request.user, obj.domain):
            return True
        return obj.expert_id == request.user.pk

    def get_form(self, request, obj=None, **kwargs):
        request._referral = obj  # the domain is fixed here, so the expert list can follow it
        return super().get_form(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "expert":
            referral = getattr(request, "_referral", None)
            kwargs["queryset"] = domain_people(referral.domain if referral else None)
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

    @admin.display(description=_("وضعیت قیمت"))
    def quote_state(self, obj):
        if obj.quoted_price is None:
            return "—"
        if obj.quote_approved_at is None:
            return "منتظر تأیید مدیر حوزه"
        who = obj.quote_approved_by.get_full_name() if obj.quote_approved_by else ""
        return f"تأیید شده{f' توسط {who}' if who else ''}"

    @admin.display(description=_("دانلود ضمیمه"))
    def attachment_link(self, obj):
        if not obj.pk or not obj.attachment:
            return "—"
        from django.urls import reverse

        return format_html('<a href="{}">دانلود فایل</a>',
                           reverse("services:attachment", args=["referral", obj.pk]))

    def save_model(self, request, obj, form, change):
        if "quoted_price" in form.changed_data:
            if obj.quoted_price is None:
                obj.quote_approved_by, obj.quote_approved_at = None, None
            else:
                services.price_set(obj, request.user)  # an expert's new price waits for a manager again
        elif form.cleaned_data.get("approve_quote") and self._may_approve_price(request, obj):
            services.approve_price(obj, request.user)
        super().save_model(request, obj, form, change)
        if "expert" in form.changed_data and obj.expert is not None:
            services.assign(obj, obj.expert, request.user)
        changed = "، ".join(name for name in form.changed_data if name != "approve_quote") if change else ""
        services.log(obj.request, request.user,
                     f"گزارش حوزه‌ی {obj.domain} به‌روز شد ({changed})." if changed
                     else f"ارجاع به حوزه‌ی {obj.domain}.")
        if not change:
            services.mark_referred(obj.request, request.user)


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

    def get_model_perms(self, request):
        # Payments belong to a request and are entered inside it; a menu entry of their own only
        # adds to the clutter. The urls stay, so links from the request page still work.
        return {}

    def save_model(self, request, obj, form, change):
        if obj.recorded_by is None:
            obj.recorded_by = request.user
        super().save_model(request, obj, form, change)
        services.log(obj.request, request.user, f"پرداخت {obj.amount:,} تومان ثبت شد.")


@admin.register(ContactChannel)
class ContactChannelAdmin(admin.ModelAdmin):
    list_display = ("kind", "label", "value", "is_active", "order")
    list_editable = ("is_active", "order")

@admin.register(HeardFromReport)
class HeardFromReportAdmin(admin.ModelAdmin):
    """
    One page, no list and no form: how people heard of us. Only site admins see it or its menu
    entry — the answers are about the business, not about any one domain's work.
    """

    def get_urls(self):
        return [path("", self.admin_site.admin_view(self.report_view), name="services_heardfromreport_changelist")]

    def report_view(self, request):
        if not is_site_admin(request.user):
            raise Http404
        period = request.GET.get("period")
        if period not in heard_from_report.PERIODS:
            period = heard_from_report.DEFAULT_PERIOD
        return render(request, "admin/services/heard_from_report.html", {
            **self.admin_site.each_context(request),
            **heard_from_report.build(period),
            "title": self.model._meta.verbose_name,
            "opts": self.model._meta,
            "period": period,
            "periods": [(key, label) for key, (_days, label) in heard_from_report.PERIODS.items()],
            "columns": [ServiceRequest.Kind.PROJECT.label, ServiceRequest.Kind.CONSULTING.label, "همکاری با ما"],
        })

    def has_module_permission(self, request):
        return is_site_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return is_site_admin(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
