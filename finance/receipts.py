"""
Keeping the ledger in step with the money: a receipt appears the moment a payment is confirmed,
follows it if it is corrected, and is voided (never deleted) if the payment is undone.
"""
from django.db import transaction
from django.utils import timezone

from accounts.roles import FINANCE_GROUP

from . import shares
from .models import Receipt

ONLINE = Receipt.Method.ONLINE


def from_order(order):
    """A paid store order: one receipt per product that cost something."""
    made = []
    for item in order.items.select_related("product"):
        if item.price <= 0 or Receipt.objects.filter(order_item=item).exists():
            continue
        made.append(Receipt.objects.create(
            source=Receipt.Source.SALE, order_item=item, product=item.product, title=item.title,
            payer=order.user, payer_name=order.user.get_full_name(), payer_mobile=order.user.mobile_number,
            amount=item.price, method=ONLINE, reference=order.reference_id, card_pan=order.card_pan,
            received_at=order.paid_at or timezone.now(),
        ))
    for receipt in made:
        _settle_in(receipt)


def void_order(order, reason):
    for receipt in Receipt.objects.filter(order_item__order=order, voided_at__isnull=True):
        void(receipt, reason)


def from_payment(payment):
    """A project order's or consultation's payment was saved: add, correct or void its receipt."""
    from services.models import RequestPayment

    receipt = Receipt.objects.filter(payment=payment).first()
    counts = payment.status == RequestPayment.Status.PAID and payment.amount > 0
    if receipt is not None and not receipt.is_void:
        if not counts:
            void(receipt, "پرداخت از حالت «پرداخت شده» خارج شد.")
        elif receipt.amount != payment.amount:
            receipt.amount = payment.amount
            receipt.save(update_fields=["amount"])
            shares.split(receipt)  # the old division was of a different sum
        return
    if not counts or receipt is not None:
        return
    request = payment.request
    receipt = Receipt.objects.create(
        source=Receipt.Source.SERVICE, payment=payment, service_request=request,
        title=f"{request.get_kind_display()} {request.tracking_code} — {payment.note or 'پرداخت'}",
        payer=request.user, payer_name=request.name, payer_mobile=request.mobile_number,
        amount=payment.amount, method=payment.method, reference=payment.reference, card_pan=payment.card_pan,
        received_at=payment.paid_at or timezone.now(),
    )
    _settle_in(receipt)


def void(receipt, reason):
    """Cancel a receipt and, with it, everybody's share of it. The row stays for the record."""
    receipt.voided_at = timezone.now()
    receipt.void_reason = reason[:250]
    receipt.save(update_fields=["voided_at", "void_reason"])
    receipt.shares.all().delete()


def _settle_in(receipt):
    shares.split(receipt)
    transaction.on_commit(lambda: announce(receipt))


def announce(receipt):
    """Tell the finance managers at once that money came in."""
    from accounts.models import User
    from inbox import services as inbox

    people = list(User.objects.filter(groups__name=FINANCE_GROUP, is_active=True).distinct())
    if not people:
        return
    who = receipt.payer_name or receipt.payer_mobile or "—"
    lines = [
        f"{receipt.title}",
        f"پرداخت‌کننده: {who}",
        f"مبلغ: {receipt.amount:,} تومان — {receipt.get_method_display()}",
    ]
    if not receipt.split_at:
        lines.append(f"سهم‌بندی نشد: {receipt.unsplit_reason}")
    inbox.send(None, f"دریافت تازه: {receipt.amount:,} تومان"[:200], "\n".join(lines), people)
