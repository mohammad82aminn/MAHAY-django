"""
Sending SMS. The backend is chosen in .env, so no code changes when a real provider is bought:

SMS_BACKEND=console   -> printed in the terminal (development)
SMS_BACKEND=disabled  -> nothing is sent; features that need SMS are switched off
SMS_BACKEND=kavenegar -> a real provider (needs SMS_API_KEY); to be filled in when bought
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class SMSError(Exception):
    """The provider refused the message."""


def backend():
    return getattr(settings, "SMS_BACKEND", "console")


def is_enabled():
    """Is SMS usable at all? (Sign-up verification is skipped when it isn't.)"""
    return backend() != "disabled"


def send(mobile_number, text):
    """Send one message. Raises SMSError if the provider fails."""
    name = backend()
    if name == "disabled":
        return
    if name == "console":
        print(f"[SMS] to {mobile_number}: {text}")  # noqa: T201 (development only)
        logger.info("SMS to %s: %s", mobile_number, text)
        return
    raise SMSError(f"سرویس پیامک «{name}» هنوز تنظیم نشده است.")


def send_verification_code(mobile_number, code):
    send(mobile_number, f"کد تأیید شما در MAHAY: {code}")