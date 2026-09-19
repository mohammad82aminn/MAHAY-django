"""
Sending SMS. The backend is chosen in .env, so no code changes when a real provider is bought:

SMS_BACKEND=console   -> printed in the terminal (development)
SMS_BACKEND=disabled  -> nothing is sent; features that need SMS are switched off
SMS_BACKEND=kavenegar -> a real provider (needs SMS_API_KEY); to be filled in when bought
"""
import logging
import sys

from django.conf import settings

logger = logging.getLogger(__name__)


class SMSError(Exception):
    """The provider refused the message."""


def backend():
    return getattr(settings, "SMS_BACKEND", "console")


def is_enabled():
    """Is SMS usable at all? (Sign-up verification is skipped when it isn't.)"""
    return backend() != "disabled"


def _echo(line):
    # A Windows console is cp1252 by default and raises on Persian text; the digits of the
    # code still come through as "?" placeholders, which is all this backend is needed for.
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(line.encode(encoding, "replace").decode(encoding))  # noqa: T201 (development only)


def send(mobile_number, text):
    """Send one message. Raises SMSError if the provider fails."""
    name = backend()
    if name == "disabled":
        return
    if name == "console":
        _echo(f"[SMS] to {mobile_number}: {text}")
        logger.info("SMS to %s: %s", mobile_number, text)
        return
    raise SMSError(f"سرویس پیامک «{name}» هنوز تنظیم نشده است.")


def send_verification_code(mobile_number, code):
    send(mobile_number, f"کد تأیید شما در MAHAY: {code}")