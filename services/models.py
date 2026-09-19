"""
Service requests: "سفارش پروژه" and "مشاوره تخصصی".

The site is the record: the visitor fills a form, then continues the conversation on
Telegram / Instagram / phone. Site admins refer the request to one or more domains;
the domain's expert fills in the price and the state of the work, and everything
(status changes, payments, messages) is kept in the request's file.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _

from content.storage import protected_storage

from .validators import validate_attachment_extension, validate_attachment_size


class ServiceRequest(models.Model):
    class Kind(models.TextChoices):
        PROJECT = "project", _("سفارش پروژه")
        CONSULTING = "consulting", _("مشاوره تخصصی")

    class Status(models.TextChoices):
        NEW = "new", _("جدید")
        REVIEWING = "reviewing", _("در حال بررسی")
        REFERRED = "referred", _("ارجاع شده")
        IN_PROGRESS = "in_progress", _("در حال انجام")
        DONE = "done", _("انجام شد")
        CANCELED = "canceled", _("لغو شد")
        REJECTED = "rejected", _("رد شد")

    class Level(models.TextChoices):
        UNIVERSITY = "university", _("درسی / دانشگاهی")
        THESIS = "thesis", _("پایان‌نامه")
        RESEARCH = "research", _("تحقیقاتی")
        INDUSTRIAL = "industrial", _("صنعتی")
        STARTUP = "startup", _("استارتاپی")
        PERSONAL = "personal", _("شخصی")

    class Need(models.TextChoices):
        FULL = "full", _("انجام کامل کار")
        PARTIAL = "partial", _("کمک در بخشی از کار")
        DEBUG = "debug", _("رفع اشکال کار موجود")
        REVIEW = "review", _("بررسی و ارزیابی")
        TRAINING = "training", _("آموزش اختصاصی")
        OTHER = "other", _("سایر")

    class Channel(models.TextChoices):
        TELEGRAM = "telegram", _("تلگرام")
        WHATSAPP = "whatsapp", _("واتساپ")
        EITAA = "eitaa", _("ایتا")
        RUBIKA = "rubika", _("روبیکا")
        PHONE = "phone", _("تماس تلفنی")

    class Source(models.TextChoices):
        SITE = "site", _("فرم سایت")
        TELEGRAM = "telegram", _("تلگرام")
        INSTAGRAM = "instagram", _("اینستاگرام")
        EITAA = "eitaa", _("ایتا")
        RUBIKA = "rubika", _("روبیکا")
        PHONE = "phone", _("تماس تلفنی")
        OTHER = "other", _("سایر")

    tracking_code = models.CharField(_("کد پیگیری"), max_length=14, unique=True, editable=False)
    kind = models.CharField(_("نوع درخواست"), max_length=12, choices=Kind.choices)
    status = models.CharField(_("وضعیت"), max_length=12, choices=Status.choices, default=Status.NEW)
    source = models.CharField(
        _("منبع"), max_length=12, choices=Source.choices, default=Source.SITE,
        help_text=_("اگر درخواست را خودتان از روی پیام کاربر ثبت می‌کنید، منبع را مشخص کنید."),
    )

    # Who is asking
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="service_requests", verbose_name=_("کاربر سایت"),
    )
    name = models.CharField(_("نام و نام خانوادگی"), max_length=150)
    mobile_number = models.CharField(_("شماره موبایل"), max_length=20)
    email = models.EmailField(_("ایمیل"), blank=True)
    contact_channel = models.CharField(_("راه ارتباطی ترجیحی"), max_length=12, choices=Channel.choices)
    contact_id = models.CharField(
        _("آیدی یا شماره در آن بستر"), max_length=150, blank=True,
        help_text=_("اگر تماس تلفنی را انتخاب کرده‌اید، لازم نیست."),
    )

    # About the work
    domains = models.ManyToManyField(
        "domains.Domain", blank=True, related_name="service_requests", verbose_name=_("حوزه‌ها"),
    )
    other_domain = models.CharField(_("حوزه‌ی دیگر"), max_length=150, blank=True)
    title = models.CharField(_("عنوان پروژه"), max_length=200)
    description = models.TextField(_("توضیحات"))
    level = models.CharField(_("سطح پروژه"), max_length=12, choices=Level.choices)
    need = models.CharField(_("چه چیزی از ما می‌خواهید"), max_length=10, choices=Need.choices)
    deadline = models.DateField(_("زمان تحویل موردنظر"), null=True, blank=True)
    attachment = models.FileField(
        _("فایل ضمیمه"), upload_to="requests/%Y/%m/", storage=protected_storage, blank=True,
        validators=[validate_attachment_extension, validate_attachment_size],
        help_text=_("شرح پروژه، عکس یا هر سندی که کمک می‌کند. فقط مدیران و کارشناس مربوطه آن را می‌بینند."),
    )

    # Money (filled in by site admins after talking to the person)
    agreed_amount = models.PositiveIntegerField(
        _("مبلغ توافق‌شده (تومان)"), null=True, blank=True, help_text=_("خالی یعنی هنوز توافقی نشده است."),
    )
    admin_note = models.TextField(_("یادداشت مدیر"), blank=True)

    # Kept only so the hourly limit can see repeat senders; nothing else reads it.
    ip_address = models.GenericIPAddressField(
        _("آی‌پی"), null=True, blank=True, editable=False, db_index=True,
    )
    created_at = models.DateTimeField(_("زمان ثبت"), auto_now_add=True)
    updated_at = models.DateTimeField(_("آخرین تغییر"), auto_now=True)

    class Meta:
        verbose_name = _("درخواست خدمات")
        verbose_name_plural = _("درخواست‌های خدمات")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.tracking_code} — {self.title}"

    def save(self, *args, **kwargs):
        if not self.tracking_code:
            self.tracking_code = self._new_code()
        super().save(*args, **kwargs)

    def _new_code(self):
        prefix = "PR" if self.kind == self.Kind.PROJECT else "CS"
        while True:
            code = f"{prefix}-{timezone.now():%y%m}-{get_random_string(4, '0123456789')}"
            if not ServiceRequest.objects.filter(tracking_code=code).exists():
                return code

    # --- Money ------------------------------------------------------------------

    @property
    def paid_total(self):
        return RequestPayment.objects.filter(request=self).aggregate(total=models.Sum("amount"))["total"] or 0

    @property
    def remaining(self):
        if self.agreed_amount is None:
            return None
        return max(0, self.agreed_amount - self.paid_total)

    @property
    def payment_state(self):
        if self.agreed_amount is None:
            return "مبلغ تعیین نشده"
        paid = self.paid_total
        if paid == 0:
            return "پرداخت نشده"
        if paid >= self.agreed_amount:
            return "تسویه شده"
        return "پرداخت جزئی"

    @property
    def quoted_total(self):
        """Sum of the prices the experts suggested for their parts."""
        return Referral.objects.filter(request=self).aggregate(
            total=models.Sum("quoted_price")
        )["total"] or 0


class Referral(models.Model):
    """A request handed to one domain. Its expert fills in price and progress."""

    class Status(models.TextChoices):
        REFERRED = "referred", _("ارجاع شده")
        REVIEWING = "reviewing", _("در حال بررسی")
        IN_PROGRESS = "in_progress", _("در حال انجام")
        DONE = "done", _("انجام شد")
        NOT_FEASIBLE = "not_feasible", _("امکان‌پذیر نیست")

    request = models.ForeignKey(
        ServiceRequest, on_delete=models.CASCADE, related_name="referrals", verbose_name=_("درخواست"),
    )
    domain = models.ForeignKey(
        "domains.Domain", on_delete=models.PROTECT, related_name="referrals", verbose_name=_("حوزه"),
    )
    expert = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="referrals", verbose_name=_("کارشناس"),
        help_text=_("یکی از مدیران همین حوزه. خالی یعنی هنوز شخص مشخص نشده است."),
    )
    status = models.CharField(_("وضعیت"), max_length=12, choices=Status.choices, default=Status.REFERRED)

    # Filled in by the expert
    quoted_price = models.PositiveIntegerField(_("قیمت پیشنهادی این بخش (تومان)"), null=True, blank=True)
    duration_text = models.CharField(_("مدت زمان تقریبی"), max_length=100, blank=True, help_text=_("مثلاً ۳ هفته"))
    done_work = models.TextField(_("کارهای انجام‌شده"), blank=True)
    remaining_work = models.TextField(_("کارهای باقی‌مانده"), blank=True)
    feasibility = models.TextField(_("ارزیابی امکان‌پذیری"), blank=True)
    attachment = models.FileField(
        _("فایل ضمیمه"), upload_to="referrals/%Y/%m/", storage=protected_storage, blank=True,
    )

    referred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False,
        related_name="made_referrals", verbose_name=_("ارجاع‌دهنده"),
    )
    created_at = models.DateTimeField(_("زمان ارجاع"), auto_now_add=True)
    updated_at = models.DateTimeField(_("آخرین تغییر"), auto_now=True)

    class Meta:
        verbose_name = _("ارجاع به حوزه")
        verbose_name_plural = _("ارجاع‌ها")
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(fields=("request", "domain"), name="services_one_referral_per_domain"),
        ]

    def __str__(self):
        return f"{self.request.tracking_code} → {self.domain}"


class RequestPayment(models.Model):
    """One payment of a request: prepayment, milestone, settlement."""

    class Method(models.TextChoices):
        ONLINE = "online", _("درگاه پرداخت")
        CARD = "card", _("کارت به کارت")
        CASH = "cash", _("نقدی")
        OTHER = "other", _("سایر")

    request = models.ForeignKey(
        ServiceRequest, on_delete=models.CASCADE, related_name="payments", verbose_name=_("درخواست"),
    )
    amount = models.PositiveIntegerField(_("مبلغ (تومان)"))
    method = models.CharField(_("روش پرداخت"), max_length=10, choices=Method.choices, default=Method.CARD)
    paid_at = models.DateTimeField(_("زمان پرداخت"), default=timezone.now)
    reference = models.CharField(_("شماره پیگیری"), max_length=100, blank=True)
    note = models.CharField(_("توضیح"), max_length=200, blank=True, help_text=_("مثلاً پیش‌پرداخت"))
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False,
        related_name="recorded_payments", verbose_name=_("ثبت‌کننده"),
    )

    class Meta:
        verbose_name = _("پرداخت درخواست")
        verbose_name_plural = _("پرداخت‌های درخواست")
        ordering = ("paid_at",)

    def __str__(self):
        return f"{self.amount:,} تومان — {self.request.tracking_code}"


class RequestMessage(models.Model):
    """Message inside the request's file: site admins and the referred experts talk here."""

    request = models.ForeignKey(
        ServiceRequest, on_delete=models.CASCADE, related_name="messages", verbose_name=_("درخواست"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="request_messages", verbose_name=_("نویسنده"),
    )
    body = models.TextField(_("متن پیام"))
    created_at = models.DateTimeField(_("زمان"), auto_now_add=True)

    class Meta:
        verbose_name = _("پیام پرونده")
        verbose_name_plural = _("پیام‌های پرونده")
        ordering = ("created_at",)

    def __str__(self):
        return f"{self.author} — {self.created_at:%Y/%m/%d %H:%M}"


class RequestEvent(models.Model):
    """Automatic history: who did what, when. Never edited by hand."""

    request = models.ForeignKey(
        ServiceRequest, on_delete=models.CASCADE, related_name="events", verbose_name=_("درخواست"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="request_events", verbose_name=_("انجام‌دهنده"),
    )
    text = models.CharField(_("رویداد"), max_length=255)
    created_at = models.DateTimeField(_("زمان"), auto_now_add=True)

    class Meta:
        verbose_name = _("رویداد پرونده")
        verbose_name_plural = _("سابقه‌ی پرونده")
        ordering = ("-created_at",)

    def __str__(self):
        return self.text


class ContactChannel(models.Model):
    """Our own contact IDs, shown on the service pages. Edited in the admin panel."""

    class Kind(models.TextChoices):
        TELEGRAM = "telegram", _("تلگرام")
        INSTAGRAM = "instagram", _("اینستاگرام")
        WHATSAPP = "whatsapp", _("واتساپ")
        EITAA = "eitaa", _("ایتا")
        RUBIKA = "rubika", _("روبیکا")
        PHONE = "phone", _("تماس تلفنی")
        EMAIL = "email", _("ایمیل")

    kind = models.CharField(_("بستر"), max_length=12, choices=Kind.choices)
    label = models.CharField(_("عنوان نمایشی"), max_length=100, help_text=_("مثلاً پشتیبانی MAHAY"))
    value = models.CharField(_("آیدی یا شماره"), max_length=150, help_text=_("مثلاً @mahay_support یا 09121234567"))
    url = models.URLField(_("لینک"), blank=True, help_text=_("اگر خالی باشد، برای بسترهای شناخته‌شده خودکار ساخته می‌شود."))
    is_active = models.BooleanField(_("فعال"), default=True)
    order = models.PositiveSmallIntegerField(_("ترتیب"), default=0)

    class Meta:
        verbose_name = _("راه ارتباطی")
        verbose_name_plural = _("راه‌های ارتباطی")
        ordering = ("order", "kind")

    def __str__(self):
        return f"{self.Kind(self.kind).label}: {self.value}"

    @property
    def link(self):
        if self.url:
            return self.url
        handle = self.value.lstrip("@")
        templates = {
            self.Kind.TELEGRAM: f"https://t.me/{handle}",
            self.Kind.INSTAGRAM: f"https://instagram.com/{handle}",
            self.Kind.WHATSAPP: f"https://wa.me/{handle.lstrip('+')}",
            self.Kind.EITAA: f"https://eitaa.com/{handle}",
            self.Kind.RUBIKA: f"https://rubika.ir/{handle}",
            self.Kind.PHONE: f"tel:{self.value}",
            self.Kind.EMAIL: f"mailto:{self.value}",
        }
        return templates.get(self.Kind(self.kind), "")