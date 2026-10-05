"""
Paying for a request through the site.

The amount is never taken from the browser: it is worked out here from the agreed total and what
has already been confirmed, so a changed form field cannot buy a project for a thousand tomans.
Money is only ever counted once the gateway itself confirms it — arriving back at the callback
url proves only that somebody visited a url.
"""
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_noop

from commerce import gateway

from .models import RequestPayment
from .services import log


class PaymentNotAllowed(Exception):
    """The request is not at a point where a payment makes sense (its message is safe to show)."""


def payable_by(user, request_object):
    """A request is paid for by the person it belongs to, nobody else."""
    return (
        user.is_authenticated
        and request_object.user_id == user.pk
        and request_object.due_now > 0
    )


def label_for(request_object):
    return "پیش‌پرداخت" if request_object.paid_total == 0 else "تسویه"


@transaction.atomic
def start(request_object, callback_url):
    """
    Open a payment at the gateway and keep a pending row for it.

    Returns the url to send the customer to. Any earlier pending attempt on this request is
    abandoned first, so a customer who walked away from the gateway and came back does not end
    up with two open attempts that could both be confirmed.
    """
    amount = request_object.due_now
    if amount <= 0:
        raise PaymentNotAllowed(gettext_noop("در حال حاضر مبلغی برای پرداخت وجود ندارد."))

    RequestPayment.objects.filter(
        request=request_object, status=RequestPayment.Status.PENDING,
    ).update(status=RequestPayment.Status.FAILED, gateway_message="رها شد")

    payment = RequestPayment.objects.create(
        request=request_object,
        amount=amount,
        method=RequestPayment.Method.ONLINE,
        status=RequestPayment.Status.PENDING,
        note=label_for(request_object),
    )
    authority, payment_url = gateway.start(
        amount=amount,
        description=f"{request_object.get_kind_display()} {request_object.tracking_code} — MAHAY",
        mobile=request_object.mobile_number,
        reference=request_object.tracking_code,
        callback_url=callback_url,
    )
    payment.authority = authority
    payment.save(update_fields=["authority"])
    return payment, payment_url


@transaction.atomic
def settle(payment, data):
    """Mark a confirmed payment as received. Safe to call twice: the second time changes nothing."""
    if payment.status == RequestPayment.Status.PAID:
        return payment

    payment.status = RequestPayment.Status.PAID
    payment.paid_at = timezone.now()
    payment.reference = str(data.get("ref_id", ""))
    payment.card_pan = str(data.get("card_pan", ""))
    payment.gateway_message = str(data.get("message", ""))[:255]
    payment.save(update_fields=["status", "paid_at", "reference", "card_pan", "gateway_message"])

    log(payment.request, None, f"{payment.note} {payment.amount:,} تومان از درگاه پرداخت شد.")
    return payment


def fail(payment, message):
    if payment.status != RequestPayment.Status.PENDING:
        return payment
    payment.status = RequestPayment.Status.FAILED
    payment.gateway_message = message[:255]
    payment.save(update_fields=["status", "gateway_message"])
    return payment
