"""Helpers shared by the views and the admin panel."""
from datetime import timedelta

from django.utils import timezone

from accounts.roles import is_site_admin

from .models import Referral, RequestEvent, ServiceRequest

MAX_PER_HOUR = 3  # requests per hour from one mobile number
MAX_PER_IP_PER_HOUR = 10  # ...and from one address, since the number alone is free to invent


def log(request_object, actor, text):
    RequestEvent.objects.create(request=request_object, actor=actor, text=text)


def too_many_requests(mobile_number, ip_address):
    """
    The form needs no account, so the mobile number in it proves nothing: anyone refused on
    one number can invent the next. The address the request came from is therefore counted
    as well, with a looser limit because a university or office shares one.
    """
    since = timezone.now() - timedelta(hours=1)
    recent = ServiceRequest.objects.filter(created_at__gte=since)
    if recent.filter(mobile_number=mobile_number).count() >= MAX_PER_HOUR:
        return True
    return bool(ip_address) and recent.filter(ip_address=ip_address).count() >= MAX_PER_IP_PER_HOUR


def visible_requests(user):
    """Site admins see everything; a domain manager sees only what was referred to their domains."""
    if is_site_admin(user):
        return ServiceRequest.objects.all()
    return ServiceRequest.objects.filter(referrals__domain__group__user=user).distinct()


def visible_referrals(user):
    if is_site_admin(user):
        return Referral.objects.all()
    return Referral.objects.filter(domain__group__user=user)


def can_read(user, request_object):
    return visible_requests(user).filter(pk=request_object.pk).exists()