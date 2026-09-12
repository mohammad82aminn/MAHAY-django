"""
ZarinPal payment gateway.

Two modes, chosen by settings (see .env):
- ZARINPAL_MODE=sandbox  -> the sandbox gateway; no real money moves
- ZARINPAL_MODE=live     -> the real gateway (needs a merchant id)
Amounts are sent in Rial: ZarinPal works in Rial, our prices are in Toman (1 Toman = 10 Rial).
"""
import requests
from django.conf import settings

TIMEOUT = 20  # seconds
RIAL_PER_TOMAN = 10

SANDBOX = "https://sandbox.zarinpal.com/pg/"
LIVE = "https://payment.zarinpal.com/pg/"


class PaymentError(Exception):
    """The gateway refused the request (its message is safe to show to the user)."""


def _base():
    return SANDBOX if getattr(settings, "ZARINPAL_MODE", "sandbox") == "sandbox" else LIVE


def payment_page(authority):
    return f"{_base()}StartPay/{authority}"


def _post(path, payload):
    payload["merchant_id"] = settings.ZARINPAL_MERCHANT_ID
    try:
        response = requests.post(f"{_base()}v4/payment/{path}", json=payload, timeout=TIMEOUT)
        body = response.json()
    except (requests.RequestException, ValueError) as error:
        raise PaymentError("ارتباط با درگاه پرداخت برقرار نشد. چند لحظه بعد دوباره تلاش کنید.") from error

    data = body.get("data") or {}
    if data:
        return data
    errors = body.get("errors") or {}
    message = errors.get("message") if isinstance(errors, dict) else None
    raise PaymentError(message or "درگاه پرداخت درخواست را نپذیرفت.")


def request_payment(order, callback_url):
    """Ask the gateway for an authority code; returns (authority, payment page url)."""
    data = _post("request.json", {
        "amount": order.total * RIAL_PER_TOMAN,
        "callback_url": callback_url,
        "description": f"سفارش {order.number} — MAHAY",
        "metadata": {"mobile": str(order.user.mobile_number), "order_id": order.number},
    })
    authority = data.get("authority")
    if not authority:
        raise PaymentError("درگاه پرداخت کد پیگیری نداد.")
    return authority, payment_page(authority)


def verify_payment(order):
    """Confirm the payment with the gateway. Returns the gateway data, or raises PaymentError."""
    return _post("verify.json", {
        "amount": order.total * RIAL_PER_TOMAN,
        "authority": order.authority,
    })