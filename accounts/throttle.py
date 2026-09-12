"""
Login throttling: stops password guessing (brute force).

- MAX_PER_NUMBER failures for one mobile number -> that number is blocked for WINDOW
- MAX_PER_IP failures from one IP -> that IP is blocked (someone trying many accounts)
A successful login clears the number's failures, so normal users never notice this.
"""
from datetime import timedelta

from django.utils import timezone

from .models import LoginAttempt

WINDOW = timedelta(minutes=15)
MAX_PER_NUMBER = 5
MAX_PER_IP = 20


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:  # behind nginx: the first address is the real visitor
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _recent(**filters):
    return LoginAttempt.objects.filter(created_at__gte=timezone.now() - WINDOW, **filters)


def minutes_blocked(mobile_number, ip_address):
    """0 if login may be tried, otherwise how many minutes are left."""
    for count, filters in ((MAX_PER_NUMBER, {"mobile_number": mobile_number}),
                           (MAX_PER_IP, {"ip_address": ip_address})):
        if not filters.get("mobile_number") and not filters.get("ip_address"):
            continue
        rows = _recent(**filters).order_by("-created_at")[:count]
        if len(rows) >= count:
            passed = timezone.now() - rows[count - 1].created_at
            return max(1, int((WINDOW - passed).total_seconds() // 60) + 1)
    return 0


def record_failure(mobile_number, ip_address):
    LoginAttempt.objects.create(mobile_number=mobile_number or "", ip_address=ip_address)


def clear(mobile_number):
    LoginAttempt.objects.filter(mobile_number=mobile_number).delete()