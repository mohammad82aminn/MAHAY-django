"""
The 48-hour reminders: work that has waited on somebody that long is named to them, and to the
site admins, in the کارپوشه. Run every hour by cron (`python manage.py send_reminders`).

What counts as waiting, and on whom:
- content «منتظر مدیر حوزه»  -> the domain's managers
- content «منتظر مدیر کل»    -> the site admins
- a referral with no expert  -> the domain's managers (the site admins, where it has none)
- an expert's price not yet agreed to -> the domain's managers
- work handed to an expert who hasn't started it -> that expert
- a technical request nobody has picked up -> the technical team

The site admins hear about all of it. Each person gets one message listing everything overdue,
not one message per item, and each item is reminded once per step (inbox.models.Reminder).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Q
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import SITE_ADMINS_GROUP
from products.templatetags.store import fa_num

from . import services as inbox
from .models import Reminder

REMIND_AFTER = timedelta(hours=48)


@dataclass
class Overdue:
    key: str  # the item and the moment it started waiting at this step
    text: str
    url: str
    people: set = field(default_factory=set)


def site_admins():
    """The site admins (not the technical admins): they oversee the flow of work."""
    return set(User.objects.filter(Q(is_superuser=True) | Q(groups__name=SITE_ADMINS_GROUP), is_active=True).distinct())


def active_managers(domain):
    return {user for user in domain.managers_group.user_set.all() if user.is_active}


def overdue(now=None):
    cutoff = (now or timezone.now()) - REMIND_AFTER
    return [*_content(cutoff), *_referrals(cutoff), *_tech_requests(cutoff)]


def _tech_requests(cutoff):
    """A technical request nobody has picked up: the technical team."""
    from support.models import TechRequest
    from support.services import tech_team, url_of

    waiting = list(TechRequest.objects.filter(status=TechRequest.Status.NEW, created_at__lte=cutoff))
    team = set(tech_team()) if waiting else set()
    for request in waiting:
        yield Overdue(f"tech:{request.pk}:{request.created_at.isoformat()}",
                      f"درخواست فنی «{request.title}» — هنوز برداشته نشده", url_of(request), team)


def _content(cutoff):
    from approvals.models import ChangeRequest
    from approvals.services import admin_url

    waiting = (
        ChangeRequest.objects.filter(status=ChangeRequest.Status.PENDING, stage_since__lte=cutoff)
        .select_related("domain__managers_group", "content_type")
        .prefetch_related("domain__managers_group__user_set")
    )
    for request in waiting:
        people = set()
        if request.stage == ChangeRequest.Stage.DOMAIN and request.domain is not None:
            people = active_managers(request.domain)
        yield Overdue(
            key=f"change:{request.pk}:{request.stage}:{request.stage_since.isoformat()}",
            text=f"«{request.object_repr}» ({request.get_action_display()}) — {request.get_stage_display()}",
            url=admin_url(request) or reverse("admin:approvals_changerequest_change", args=[request.pk]),
            people=people,
        )


def _referrals(cutoff):
    from services.models import Referral, ServiceRequest

    closed = (ServiceRequest.Status.DONE, ServiceRequest.Status.CANCELED, ServiceRequest.Status.REJECTED)
    # Only rows already past the mark come back from the database; the loop below just words them
    past_the_mark = (
        Q(expert__isnull=True, created_at__lte=cutoff)
        | Q(expert__isnull=False, quoted_price__isnull=False, quote_approved_at__isnull=True, price_since__lte=cutoff)
        | Q(expert__isnull=False, quoted_price__isnull=True, status=Referral.Status.REFERRED, start_since__lte=cutoff)
        | Q(expert__isnull=False, quote_approved_at__isnull=False, status=Referral.Status.REFERRED, start_since__lte=cutoff)
    )
    referrals = (
        Referral.objects.exclude(request__status__in=closed)
        .annotate(price_since=Coalesce("quoted_at", "updated_at"), start_since=Coalesce("assigned_at", "created_at"))
        .filter(past_the_mark)
        .select_related("request", "domain__managers_group", "expert")
        .prefetch_related("domain__managers_group__user_set")
    )
    for referral in referrals:
        where = f"{referral.request.tracking_code} — «{referral.request.title}»، حوزه‌ی {referral.domain}"
        url = reverse("admin:services_referral_change", args=[referral.pk])
        managers = active_managers(referral.domain)
        if referral.expert_id is None:
            if referral.created_at <= cutoff:
                yield Overdue(f"assign:{referral.pk}:{referral.created_at.isoformat()}",
                              f"{where} — منتظر انتخاب کارشناس", url, managers)
        elif referral.quoted_price is not None and referral.quote_approved_at is None:
            since = referral.quoted_at or referral.updated_at
            if since <= cutoff:
                yield Overdue(f"quote:{referral.pk}:{since.isoformat()}",
                              f"{where} — منتظر تأیید قیمت", url, managers)
        elif referral.status == Referral.Status.REFERRED:
            since = referral.assigned_at or referral.created_at
            if since <= cutoff and referral.expert.is_active:
                yield Overdue(f"start:{referral.pk}:{since.isoformat()}",
                              f"{where} — هنوز شروع نشده", url, {referral.expert})


def send_due(now=None):
    """Send what has become due since the last run. Returns how many messages went out."""
    due = overdue(now)
    already = set(Reminder.objects.filter(key__in=[item.key for item in due]).values_list("key", flat=True))
    due = [item for item in due if item.key not in already]
    if not due:
        return 0

    admins = site_admins()
    per_person = defaultdict(list)
    for item in due:
        for person in item.people | admins:
            per_person[person].append(item)

    for person, items in sorted(per_person.items(), key=lambda pair: pair[0].pk):
        lines = ["این کارها بیش از ۴۸ ساعت منتظر مانده‌اند:", ""]
        for item in items:
            lines += [f"• {item.text}", f"  {item.url}"]
        inbox.send(None, f"یادآوری: {fa_num(len(items))} کار منتظر رسیدگی", "\n".join(lines), [person])
    Reminder.objects.bulk_create([Reminder(key=item.key) for item in due], ignore_conflicts=True)
    return len(per_person)
