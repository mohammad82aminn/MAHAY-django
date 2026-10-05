"""
One-time codes sent by SMS (sign-up verification today; password reset later).

Rules:
- a code is 6 digits and expires after CODE_TTL
- a code dies after MAX_ATTEMPTS wrong tries, so it can't be guessed
- a number may receive at most MAX_PER_HOUR codes, so nobody can burn our SMS credit
- codes are stored hashed: a database leak must not hand out working codes
"""
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext as _

from . import sms
from .models import VerificationCode

CODE_LENGTH = 6
CODE_TTL = timedelta(minutes=2)
# Someone resetting a password is usually away from the sign-up flow and reads the message later,
# and a real SMS provider adds its own delay, so that code is given longer to be useful.
RESET_CODE_TTL = timedelta(minutes=5)
RESEND_AFTER = timedelta(seconds=90)
MAX_ATTEMPTS = 5
MAX_PER_HOUR = 5


def ttl_for(purpose):
    return RESET_CODE_TTL if purpose == VerificationCode.Purpose.PASSWORD_RESET else CODE_TTL


class TooManyRequests(Exception):
    """The number asked for too many codes; the message says when to try again."""


def _recent(mobile_number, purpose):
    return VerificationCode.objects.filter(
        mobile_number=mobile_number, purpose=purpose, created_at__gte=timezone.now() - timedelta(hours=1),
    )


def seconds_until_resend(mobile_number, purpose):
    """0 when a new code may be sent, otherwise the wait in seconds."""
    last = VerificationCode.objects.filter(mobile_number=mobile_number, purpose=purpose).first()
    if last is None:
        return 0
    passed = timezone.now() - last.created_at
    return max(0, int((RESEND_AFTER - passed).total_seconds()))


def create_and_send(mobile_number, purpose=VerificationCode.Purpose.SIGNUP):
    """Make a code, send it, and return it (the caller only shows it when DEBUG is on)."""
    wait = seconds_until_resend(mobile_number, purpose)
    if wait:
        raise TooManyRequests(_("برای ارسال کد جدید %(seconds)s ثانیه صبر کنید.") % {"seconds": wait})
    if _recent(mobile_number, purpose).count() >= MAX_PER_HOUR:
        raise TooManyRequests(_("تعداد درخواست‌های شما زیاد است. یک ساعت دیگر تلاش کنید."))

    code = get_random_string(CODE_LENGTH, "0123456789")
    VerificationCode.objects.filter(mobile_number=mobile_number, purpose=purpose, used_at=None).update(
        used_at=timezone.now()  # older codes of this number stop working
    )
    VerificationCode.objects.create(
        mobile_number=mobile_number, purpose=purpose, code_hash=make_password(code),
        expires_at=timezone.now() + ttl_for(purpose),
    )
    sms.send_verification_code(mobile_number, code)
    return code


def verify(mobile_number, purpose, code):
    """True if the code is right, fresh and unused. Wrong tries are counted."""
    row = VerificationCode.objects.filter(
        mobile_number=mobile_number, purpose=purpose, used_at=None, expires_at__gt=timezone.now(),
    ).first()
    if row is None or row.attempts >= MAX_ATTEMPTS:
        return False

    if not check_password(str(code).strip(), row.code_hash):
        row.attempts += 1
        if row.attempts >= MAX_ATTEMPTS:
            row.used_at = timezone.now()  # burnt: the user must ask for a new code
        row.save(update_fields=["attempts", "used_at"])
        return False

    row.used_at = timezone.now()
    row.save(update_fields=["used_at"])
    return True