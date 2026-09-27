"""Helpers shared by the views and the admin panel."""
from datetime import timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.roles import is_site_admin
from domains.access import has_managers, is_manager, managed_domains

from .models import Referral, RequestEvent, ServiceRequest

MAX_PER_HOUR = 3  # requests per hour from one mobile number
MAX_PER_IP_PER_HOUR = 10  # ...and from one address, since the number alone is free to invent


def log(request_object, actor, text):
    RequestEvent.objects.create(request=request_object, actor=actor, text=text)


def mark_referred(request_object, actor=None):
    """
    A request just handed to a domain is not «جدید» any more.

    The panel marks untouched requests in red, and handing one to a domain is plainly touching
    it; leaving the mark on would teach people to ignore it. Only that first state moves — a
    request already in progress, finished or cancelled keeps whatever it says.
    """
    if request_object.status != ServiceRequest.Status.NEW:
        return False
    request_object.status = ServiceRequest.Status.REFERRED
    request_object.save(update_fields=["status", "updated_at"])
    log(request_object, actor, "با ارجاع به حوزه، وضعیت به «ارجاع شده» تغییر کرد.")
    return True


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
    """
    Site admins see everything; a domain manager what was referred to their domains; an expert
    only the requests whose work was handed to them, not their colleagues'.
    """
    if is_site_admin(user):
        return ServiceRequest.objects.all()
    return ServiceRequest.objects.filter(pk__in=visible_referrals(user).values("request"))


# Where a request has got to, worked out from what it already holds rather than stored: a saved
# stage would be one more thing to keep in step, and it would quietly go wrong.
STAGE_REVIEW = ("review", "منتظر بررسی و ارجاع", "شما")
STAGE_ASSIGN = ("assign", "منتظر انتخاب کارشناس", "مدیر حوزه")
STAGE_ASSIGN_ADMIN = ("assign", "منتظر انتخاب کارشناس", "شما")  # a domain with no manager
STAGE_QUOTES = ("quotes", "منتظر قیمت حوزه‌ها", "کارشناس")
STAGE_QUOTE_REVIEW = ("quote_review", "منتظر تأیید قیمت", "مدیر حوزه")
STAGE_AMOUNT = ("amount", "منتظر تعیین مبلغ کل", "شما")
STAGE_PREPAY = ("prepay", "منتظر پیش‌پرداخت", "مشتری")
STAGE_WORKING = ("working", "در حال انجام", "کارشناس")
STAGE_SETTLE = ("settle", "منتظر تسویه", "مشتری")
STAGE_DONE = ("done", "تمام شد", "—")
STAGE_CLOSED = ("closed", "بسته شد", "—")


def stage_of(request_object):
    """
    The step a request is on, as (key, label, whose turn it is).

    Read top to bottom: the first condition that holds is where the work actually sits.
    """
    if request_object.status in (request_object.Status.CANCELED, request_object.Status.REJECTED):
        return STAGE_CLOSED

    referrals = list(request_object.referrals.all())

    # A settled total is the pivot: before it the question is who prices the work, after it the
    # question is money. Asking a customer who already owes us to wait for a referral would be
    # telling them the wrong thing.
    if request_object.agreed_amount is None:
        if not referrals:
            return STAGE_REVIEW
        unassigned = [referral for referral in referrals if referral.expert_id is None]
        if unassigned:
            if all(domain_has_managers(referral) for referral in unassigned):
                return STAGE_ASSIGN
            return STAGE_ASSIGN_ADMIN
        if any(referral.quoted_price is None for referral in referrals):
            return STAGE_QUOTES
        if any(referral.quote_approved_at is None for referral in referrals):
            return STAGE_QUOTE_REVIEW
        return STAGE_AMOUNT

    if request_object.paid_total == 0:
        return STAGE_PREPAY
    if request_object.remaining == 0:
        return STAGE_DONE
    everything_done = all(referral.status == referral.Status.DONE for referral in referrals)
    return STAGE_SETTLE if everything_done else STAGE_WORKING


def price_consultation(request_object):
    """
    Put the rate on a consultation as soon as it arrives.

    A consultation is sold at a published price, so there is nothing to negotiate and no reason
    to make somebody wait for a quote they could already read. Called after the domains are
    saved, since the rate comes from the domain. Leaves a project alone.
    """
    price = request_object.consulting_price
    if price is None or request_object.agreed_amount is not None:
        return False
    request_object.agreed_amount = price
    request_object.save(update_fields=["agreed_amount", "updated_at"])
    return True


def claim_guest_requests(user):
    """
    Hand a new account the requests that were sent from its own number.

    The form takes guests, but paying needs an account, so without this a visitor who filled the
    form and signed up afterwards could never reach their own request. Matching on the number is
    safe because signing up proves it by SMS code.
    """
    return ServiceRequest.objects.filter(
        user__isnull=True, mobile_number=user.mobile_number,
    ).update(user=user)


def domain_people(domain=None):
    """
    Who a referral may be handed to: the managers and experts of one domain, or of any domain.

    Customers are never in here — the expert picker used to search every registered user, which
    put the whole customer list in front of whoever was making a referral.
    """
    from accounts.models import User

    in_a_domain = Q(groups__managers_domain__isnull=False) | Q(groups__experts_domain__isnull=False)
    people = User.objects.filter(in_a_domain, is_active=True)
    if domain is not None:
        people = User.objects.filter(is_active=True, groups__in=domain.groups)
    return people.distinct()


def visible_referrals(user):
    """The whole domain's share for its managers; for an expert, what was handed to them."""
    if is_site_admin(user):
        return Referral.objects.all()
    if not user.is_authenticated:
        return Referral.objects.none()
    return Referral.objects.filter(Q(domain__in=managed_domains(user)) | Q(expert=user))


def domain_has_managers(referral):
    """Read from the list's own annotation when there is one (see ServiceRequestAdmin), so a
    page of requests doesn't ask it once per row."""
    known = getattr(referral, "domain_has_managers", None)
    return has_managers(referral.domain) if known is None else known


def may_assign(user, referral):
    """A domain's managers pick who does its share; where it has none, a site admin does."""
    if is_manager(user, referral.domain):
        return True
    return is_site_admin(user) and not has_managers(referral.domain)


def assign(referral, expert, actor):
    """Hand the work to an expert, and tell them at once."""
    from inbox import services as inbox

    referral.assigned_at = timezone.now()
    referral.save(update_fields=["assigned_at"])

    log(referral.request, actor, f"کار حوزه‌ی {referral.domain} به {expert.get_full_name() or expert} سپرده شد.")
    if expert != actor:
        inbox.send(
            None, f"کار تازه: {referral.request.tracking_code}",
            f"«{referral.request.title}» در حوزه‌ی {referral.domain} به شما سپرده شد.\n"
            f"برای دیدن و ثبت قیمت: {reverse('admin:services_referral_change', args=[referral.pk])}",
            [expert],
        )


def price_set(referral, actor, now=None):
    """
    Someone just put a price on the domain's share. A domain manager or a site admin setting it
    has agreed to it by doing so, and so has everybody in a domain with no manager; an expert's
    price waits for a manager.
    """
    agreed = is_manager(actor, referral.domain) or is_site_admin(actor) or not has_managers(referral.domain)
    referral.quoted_at = now or timezone.now()
    referral.quote_approved_by = actor if agreed else None
    referral.quote_approved_at = (now or timezone.now()) if agreed else None


def approve_price(referral, manager):
    referral.quote_approved_by = manager
    referral.quote_approved_at = timezone.now()
    log(referral.request, manager, f"قیمت حوزه‌ی {referral.domain} ({referral.quoted_price:,} تومان) تأیید شد.")


def can_read(user, request_object):
    return visible_requests(user).filter(pk=request_object.pk).exists()