"""
Where the ledger hears about money. Listening to the saves, rather than being called from each place
that takes a payment, means a payment confirmed by the gateway, one typed in on a request's page and
one corrected later all reach the ledger the same way.
"""
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from commerce.models import Order
from domains.models import Domain
from services.models import RequestPayment

from . import receipts
from .models import DomainShareRule


@receiver(post_save, sender=Order)
def order_saved(sender, instance, **kwargs):
    if instance.status == Order.Status.PAID:
        receipts.from_order(instance)
    else:
        receipts.void_order(instance, f"سفارش به وضعیت «{instance.get_status_display()}» رفت.")


@receiver(post_save, sender=RequestPayment)
def payment_saved(sender, instance, **kwargs):
    receipts.from_payment(instance)


@receiver(pre_delete, sender=RequestPayment)
def payment_deleted(sender, instance, **kwargs):
    # Before the delete: by post_delete the receipt's link to the payment has already been cleared
    from .models import Receipt

    for receipt in Receipt.objects.filter(payment_id=instance.pk, voided_at__isnull=True):
        receipts.void(receipt, "پرداخت حذف شد.")


@receiver(post_save, sender=Domain)
def domain_saved(sender, instance, created, **kwargs):
    if created:
        DomainShareRule.objects.get_or_create(domain=instance)
