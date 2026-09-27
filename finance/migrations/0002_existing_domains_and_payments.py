from django.db import migrations
from django.utils import timezone

BEFORE = "پیش از راه‌اندازی بخش مالی دریافت شده بود؛ در صورت نیاز «سهم‌بندی دوباره» را بزنید."


def fill(apps, schema_editor):
    """
    Every domain gets its (empty) percentages, and money that came in before the ledger existed gets
    its receipt: marked as already reviewed, left undivided, and announced to nobody, so starting the
    ledger does not flood the finance managers with news of old payments.
    """
    Domain = apps.get_model("domains", "Domain")
    DomainShareRule = apps.get_model("finance", "DomainShareRule")
    Receipt = apps.get_model("finance", "Receipt")
    OrderItem = apps.get_model("commerce", "OrderItem")
    RequestPayment = apps.get_model("services", "RequestPayment")
    now = timezone.now()

    for domain in Domain.objects.all():
        DomainShareRule.objects.get_or_create(domain=domain)

    for item in OrderItem.objects.filter(order__status="paid", price__gt=0).select_related("order__user"):
        order, user = item.order, item.order.user
        Receipt.objects.get_or_create(order_item=item, defaults=dict(
            source="sale", product_id=item.product_id, title=item.title, payer=user,
            payer_name=f"{user.first_name} {user.last_name}".strip(), payer_mobile=user.mobile_number,
            amount=item.price, method="online", reference=order.reference_id, card_pan=order.card_pan,
            received_at=order.paid_at or order.created_at, reviewed_at=now, unsplit_reason=BEFORE,
        ))

    kinds = {"project": "سفارش پروژه", "consulting": "مشاوره تخصصی"}
    for payment in RequestPayment.objects.filter(status="paid", amount__gt=0).select_related("request"):
        request = payment.request
        Receipt.objects.get_or_create(payment=payment, defaults=dict(
            source="service", service_request=request,
            title=f"{kinds.get(request.kind, '')} {request.tracking_code} — {payment.note or 'پرداخت'}",
            payer_id=request.user_id, payer_name=request.name, payer_mobile=request.mobile_number,
            amount=payment.amount, method=payment.method, reference=payment.reference, card_pan=payment.card_pan,
            received_at=payment.paid_at, reviewed_at=now, unsplit_reason=BEFORE,
        ))


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0001_initial"),
        ("commerce", "0001_initial"),
        ("services", "0009_referral_waiting_since"),
        ("domains", "0003_managers_and_experts_groups"),
    ]

    operations = [
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
