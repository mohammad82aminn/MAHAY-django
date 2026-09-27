"""
The money side: every toman that comes in (Receipt), who it belongs to (Share), and what has been
paid out of it (Payout). How a receipt is divided comes from the percentages below, frozen onto the
shares at the moment it is divided, so changing a percentage later never rewrites the past.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


def percent_field(label):
    return models.DecimalField(
        label, max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(100))],
    )


class PercentSet(models.Model):
    """A group of percentages that counts only when every one of them is filled in (zero is fine)."""

    ROLES: tuple = ()

    class Meta:
        abstract = True

    def percents(self, prefix=""):
        values = {role: getattr(self, f"{prefix}{role}") for role in self.ROLES}
        return values if all(value is not None for value in values.values()) else None

    def check_total(self, prefix="", field=None):
        total = sum(getattr(self, f"{prefix}{role}") or 0 for role in self.ROLES)
        if total > 100:
            raise ValidationError({field or f"{prefix}{self.ROLES[-1]}": _(
                "جمع درصدها از ۱۰۰ بیشتر شده است؛ باقی‌مانده سهم مجموعه است."
            )})


class DomainShareRule(PercentSet):
    """A domain's usual split, one for store sales and one for project orders and consultations."""

    ROLES = ("instructor", "manager", "fund")
    SERVICE_ROLES = ("expert", "manager", "fund")

    domain = models.OneToOneField(
        "domains.Domain", on_delete=models.CASCADE, related_name="share_rule", verbose_name=_("حوزه"),
    )
    sale_instructor = percent_field(_("فروش: سهم مدرس ٪"))
    sale_manager = percent_field(_("فروش: سهم مدیر حوزه ٪"))
    sale_fund = percent_field(_("فروش: سهم صندوق حوزه ٪"))
    service_expert = percent_field(_("سفارش: سهم کارشناس ٪"))
    service_manager = percent_field(_("سفارش: سهم مدیر حوزه ٪"))
    service_fund = percent_field(_("سفارش: سهم صندوق حوزه ٪"))

    class Meta:
        verbose_name = _("درصدهای حوزه")
        verbose_name_plural = _("درصدهای حوزه‌ها")
        ordering = ("domain__order", "domain__name")

    def __str__(self):
        return str(self.domain)

    def sale_percents(self):
        return self.percents("sale_")

    def service_percents(self):
        values = {role: getattr(self, f"service_{role}") for role in self.SERVICE_ROLES}
        return values if all(value is not None for value in values.values()) else None

    def clean(self):
        self.check_total("sale_")
        total = sum(getattr(self, f"service_{role}") or 0 for role in self.SERVICE_ROLES)
        if total > 100:
            raise ValidationError({"service_fund": _("جمع درصدها از ۱۰۰ بیشتر شده است؛ باقی‌مانده سهم مجموعه است.")})


class ProductShareRule(PercentSet):
    """An exception for one course or project, used instead of its domain's sale percentages."""

    ROLES = ("instructor", "manager", "fund")

    product = models.OneToOneField(
        "products.Product", on_delete=models.CASCADE, related_name="share_rule", verbose_name=_("محصول"),
    )
    instructor = percent_field(_("سهم مدرس ٪"))
    manager = percent_field(_("سهم مدیر حوزه ٪"))
    fund = percent_field(_("سهم صندوق حوزه ٪"))

    class Meta:
        verbose_name = _("درصد استثنای محصول")
        verbose_name_plural = _("درصدهای استثنای محصولات")

    def __str__(self):
        return str(self.product)

    def clean(self):
        self.check_total()


class RequestShareRule(PercentSet):
    """An exception for one project order or consultation, instead of its domains' percentages."""

    ROLES = ("expert", "manager", "fund")

    request = models.OneToOneField(
        "services.ServiceRequest", on_delete=models.CASCADE, related_name="share_rule", verbose_name=_("درخواست"),
    )
    expert = percent_field(_("سهم کارشناس ٪"))
    manager = percent_field(_("سهم مدیر حوزه ٪"))
    fund = percent_field(_("سهم صندوق حوزه ٪"))

    class Meta:
        verbose_name = _("درصد استثنای سفارش")
        verbose_name_plural = _("درصدهای استثنای سفارش‌ها")

    def __str__(self):
        return str(self.request)

    def clean(self):
        self.check_total()


class Receipt(models.Model):
    """
    Money that actually arrived: one row per product in a paid order, and one per paid payment of a
    project order or consultation (online, or entered by hand). Made by the system, never by hand.
    """

    class Source(models.TextChoices):
        SALE = "sale", _("فروش دوره یا پروژه")
        SERVICE = "service", _("سفارش پروژه یا مشاوره")

    class Method(models.TextChoices):
        ONLINE = "online", _("درگاه پرداخت")
        CARD = "card", _("کارت به کارت")
        CASH = "cash", _("نقدی")
        OTHER = "other", _("سایر")

    source = models.CharField(_("منشأ"), max_length=10, choices=Source.choices)
    order_item = models.OneToOneField(
        "commerce.OrderItem", on_delete=models.SET_NULL, null=True, blank=True, related_name="receipt", editable=False,
        verbose_name=_("آیتم سفارش"),
    )
    payment = models.OneToOneField(
        "services.RequestPayment", on_delete=models.SET_NULL, null=True, blank=True, related_name="receipt", editable=False,
        verbose_name=_("پرداخت سفارش"),
    )
    product = models.ForeignKey(
        "products.Product", on_delete=models.SET_NULL, null=True, blank=True, related_name="receipts", editable=False,
        verbose_name=_("محصول"),
    )
    service_request = models.ForeignKey(
        "services.ServiceRequest", on_delete=models.SET_NULL, null=True, blank=True, related_name="receipts", editable=False,
        verbose_name=_("درخواست"),
    )
    title = models.CharField(_("بابت"), max_length=250)

    # Who paid, copied at the time so the ledger stays readable if the account changes
    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name=_("پرداخت‌کننده"),
    )
    payer_name = models.CharField(_("نام پرداخت‌کننده"), max_length=150, blank=True)
    payer_mobile = models.CharField(_("موبایل پرداخت‌کننده"), max_length=20, blank=True)

    amount = models.PositiveIntegerField(_("مبلغ (تومان)"))
    method = models.CharField(_("روش پرداخت"), max_length=10, choices=Method.choices)
    reference = models.CharField(_("شماره پیگیری"), max_length=100, blank=True)
    card_pan = models.CharField(_("شماره کارت"), max_length=30, blank=True)
    received_at = models.DateTimeField(_("زمان دریافت"))

    reviewed_at = models.DateTimeField(_("زمان بررسی"), null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name=_("بررسی‌کننده"),
    )
    split_at = models.DateTimeField(_("زمان سهم‌بندی"), null=True, blank=True)
    unsplit_reason = models.CharField(_("دلیل سهم‌بندی‌نشدن"), max_length=250, blank=True)
    voided_at = models.DateTimeField(_("زمان ابطال"), null=True, blank=True)
    void_reason = models.CharField(_("دلیل ابطال"), max_length=250, blank=True)
    created_at = models.DateTimeField(_("زمان ثبت"), auto_now_add=True)

    class Meta:
        verbose_name = _("دریافت")
        verbose_name_plural = _("دفتر دریافت‌ها")
        ordering = ("-received_at", "-id")

    def __str__(self):
        return f"{self.title} — {self.amount:,} تومان"

    @property
    def is_void(self):
        return self.voided_at is not None


class Share(models.Model):
    """One part of a receipt: whose it is and how much, with the percentage it was worked out at."""

    class Role(models.TextChoices):
        INSTRUCTOR = "instructor", _("مدرس")
        EXPERT = "expert", _("کارشناس")
        MANAGER = "manager", _("مدیر حوزه")
        FUND = "fund", _("صندوق حوزه")
        COMPANY = "company", _("مجموعه")

    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name="shares", verbose_name=_("دریافت"))
    domain = models.ForeignKey(
        "domains.Domain", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("حوزه"),
    )
    role = models.CharField(_("نقش"), max_length=10, choices=Role.choices)
    person = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="shares",
        verbose_name=_("شخص"), help_text=_("برای صندوق حوزه و سهم مجموعه خالی است."),
    )
    percent = models.DecimalField(_("درصد"), max_digits=5, decimal_places=2, null=True, blank=True)
    amount = models.PositiveIntegerField(_("مبلغ (تومان)"))

    class Meta:
        verbose_name = _("سهم")
        verbose_name_plural = _("سهم‌ها")
        indexes = [models.Index(fields=("person",)), models.Index(fields=("domain", "role"))]

    def __str__(self):
        return f"{self.get_role_display()}: {self.amount:,}"


class Payout(models.Model):
    """Money paid out of the collection, to a person or out of a domain's fund, after the bank transfer."""

    person = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="payouts",
        verbose_name=_("به شخص"),
    )
    fund = models.ForeignKey(
        "domains.Domain", on_delete=models.PROTECT, null=True, blank=True, related_name="fund_payouts",
        verbose_name=_("از صندوق حوزه"),
    )
    amount = models.PositiveIntegerField(_("مبلغ (تومان)"), validators=[MinValueValidator(1)])
    paid_on = models.DateField(_("تاریخ واریز"))
    reference = models.CharField(_("شماره پیگیری بانک"), max_length=100)
    note = models.CharField(_("توضیح"), max_length=250, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="+",
        verbose_name=_("ثبت‌کننده"),
    )
    created_at = models.DateTimeField(_("زمان ثبت"), auto_now_add=True)

    class Meta:
        verbose_name = _("تسویه")
        verbose_name_plural = _("تسویه‌ها")
        ordering = ("-paid_on", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(person__isnull=False, fund__isnull=True) | models.Q(person__isnull=True, fund__isnull=False),
                name="finance_payout_to_a_person_or_a_fund",
            ),
        ]

    def __str__(self):
        return f"{self.person or f'صندوق {self.fund}'} — {self.amount:,} تومان"

    def clean(self):
        if bool(self.person_id) == bool(self.fund_id):
            raise ValidationError(_("یا شخص را انتخاب کنید یا صندوق حوزه را، نه هر دو."))


class FinanceReport(Receipt):
    """No table: gives «گزارش‌های مالی» (income and everyone's balance) a place in the admin menu."""

    class Meta:
        proxy = True
        verbose_name = _("گزارش مالی")
        verbose_name_plural = _("گزارش‌های مالی")


class MyStatement(Share):
    """No table: «صورت‌حساب من», where each staff member sees only their own shares and payouts."""

    class Meta:
        proxy = True
        verbose_name = _("صورت‌حساب من")
        verbose_name_plural = _("صورت‌حساب من")
