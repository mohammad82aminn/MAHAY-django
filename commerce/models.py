from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _

from products.models import Product


class Cart(models.Model):
    """
    Shopping cart. A visitor without an account gets one too; its id is kept in their session
    and merged into the user's cart on login (see services.merge_carts).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        related_name="cart", verbose_name=_("کاربر"),
    )
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)
    updated_at = models.DateTimeField(_("آخرین تغییر"), auto_now=True)

    class Meta:
        verbose_name = _("سبد خرید")
        verbose_name_plural = _("سبدهای خرید")

    def __str__(self):
        return f"سبد {self.user or f'مهمان #{self.pk}'}"

    @property
    def products(self):
        """Products that can still be bought (a removed product is skipped)."""
        return Product.objects.visible().filter(cart_items__cart=self)

    @property
    def total(self):
        return sum(product.final_price for product in self.products)

    @property
    def count(self):
        return self.products.count()


class CartItem(models.Model):
    """One product in a cart. No quantity: a product is bought once."""

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items", verbose_name=_("سبد"))
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="cart_items", verbose_name=_("محصول"))
    added_at = models.DateTimeField(_("زمان افزودن"), auto_now_add=True)

    class Meta:
        verbose_name = _("آیتم سبد")
        verbose_name_plural = _("آیتم‌های سبد")
        ordering = ("added_at",)
        constraints = [
            models.UniqueConstraint(fields=("cart", "product"), name="commerce_one_cart_item_per_product"),
        ]

    def __str__(self):
        return str(self.product)


class Order(models.Model):
    """
    A checkout attempt. Prices are copied into OrderItem when the order is created,
    so a later price change never affects an order.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("در انتظار پرداخت")
        PAID = "paid", _("پرداخت شده")
        FAILED = "failed", _("ناموفق")
        CANCELED = "canceled", _("لغو شده")

    number = models.CharField(_("شماره سفارش"), max_length=12, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders", verbose_name=_("خریدار"),
    )
    status = models.CharField(_("وضعیت"), max_length=10, choices=Status.choices, default=Status.PENDING)
    total = models.PositiveIntegerField(_("مبلغ کل (تومان)"), default=0)

    # Payment gateway data
    authority = models.CharField(_("کد پیگیری درگاه"), max_length=100, blank=True, db_index=True)
    reference_id = models.CharField(_("شماره تراکنش"), max_length=100, blank=True)
    card_pan = models.CharField(_("شماره کارت"), max_length=30, blank=True)
    gateway_message = models.CharField(_("پیام درگاه"), max_length=255, blank=True)

    created_at = models.DateTimeField(_("تاریخ ثبت"), auto_now_add=True)
    paid_at = models.DateTimeField(_("زمان پرداخت"), null=True, blank=True)

    class Meta:
        verbose_name = _("سفارش")
        verbose_name_plural = _("سفارش‌ها")
        ordering = ("-created_at",)

    def __str__(self):
        return f"سفارش {self.number}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self._new_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _new_number():
        while True:
            number = f"{timezone.now():%y%m}{get_random_string(6, '0123456789')}"
            if not Order.objects.filter(number=number).exists():
                return number

    @property
    def is_free(self):
        return self.total == 0

    @transaction.atomic
    def mark_paid(self, reference_id="", card_pan="", message=""):
        """Successful payment: save the gateway data and give the user their products."""
        self.status = self.Status.PAID
        self.reference_id = reference_id
        self.card_pan = card_pan
        self.gateway_message = message
        self.paid_at = timezone.now()
        self.save()
        for item in OrderItem.objects.filter(order=self).select_related("product"):
            Purchase.objects.get_or_create(
                user=self.user, product=item.product,
                defaults={"order": self, "price": item.price},
            )


class OrderItem(models.Model):
    """A product in an order, with the price frozen at checkout time."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items", verbose_name=_("سفارش"))
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items", verbose_name=_("محصول"))
    title = models.CharField(_("عنوان"), max_length=200)  # kept even if the product is renamed later
    price = models.PositiveIntegerField(_("مبلغ (تومان)"))

    class Meta:
        verbose_name = _("آیتم سفارش")
        verbose_name_plural = _("آیتم‌های سفارش")
        constraints = [
            models.UniqueConstraint(fields=("order", "product"), name="commerce_one_order_item_per_product"),
        ]

    def __str__(self):
        return self.title


class Purchase(models.Model):
    """
    Ownership: this user may open this product's content forever,
    even if the product is later removed from the store.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="purchases", verbose_name=_("کاربر"),
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="purchases", verbose_name=_("محصول"))
    order = models.ForeignKey(
        Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchases", verbose_name=_("سفارش"),
    )
    price = models.PositiveIntegerField(_("مبلغ پرداختی (تومان)"), default=0)
    created_at = models.DateTimeField(_("تاریخ خرید"), auto_now_add=True)

    class Meta:
        verbose_name = _("خرید کاربر")
        verbose_name_plural = _("خریدهای کاربران")
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "product"), name="commerce_one_purchase_per_product"),
        ]

    def __str__(self):
        return f"{self.user} — {self.product}"

    def clean(self):
        if self.price and self.order is None:
            raise ValidationError({"order": _("خرید پولی باید به یک سفارش وصل باشد.")})