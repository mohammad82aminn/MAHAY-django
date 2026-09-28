"""
«گزارش عملکرد»: what each member of the staff did over a period, in numbers only — judging them is
a person's job. Every figure is one grouped query, so the page costs the same for five people or fifty.
"""
from collections import Counter
from datetime import timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F
from django.utils import timezone

from accounts.models import User
from accounts.roles import role_label
from approvals.models import ReviewEvent

PERIODS = {
    "30": (30, "۳۰ روز اخیر"),
    "90": (90, "۳ ماه اخیر"),
    "365": (365, "یک سال اخیر"),
    "all": (None, "از ابتدا"),
}
DEFAULT_PERIOD = "30"

COLUMNS = (
    ("submitted", "محتوای فرستاده"),
    ("approved", "تأییدشده"),
    ("rejected", "ردشده"),
    ("reviewed", "بررسی‌کرده (مدیر)"),
    ("review_hours", "میانگین زمان بررسی (ساعت)"),
    ("assigned_by", "کارشناس انتخاب‌کرده"),
    ("handed", "سفارش سپرده‌شده"),
    ("done", "سفارش انجام‌شده"),
    ("open", "سفارش در جریان (الان)"),
    ("tech_closed", "درخواست فنی بسته‌شده"),
    ("overdue", "کار معطل بیش از ۴۸ ساعت (الان)"),
)


def build(period):
    from inbox.reminders import overdue
    from services.models import Referral
    from support.models import TechRequest

    days = PERIODS[period][0]
    since = timezone.now() - timedelta(days=days) if days else None

    def recent(queryset, field):
        return queryset.filter(**{f"{field}__gte": since}) if since else queryset

    def per(queryset, key):
        return dict(queryset.values_list(key).annotate(n=Count("pk")).order_by())

    events = recent(ReviewEvent.objects.all(), "created_at")
    decided = events.filter(kind__in=(ReviewEvent.Kind.APPROVED, ReviewEvent.Kind.REJECTED), change_request__isnull=False)
    reviews = (
        events.filter(kind__in=(ReviewEvent.Kind.FORWARDED, ReviewEvent.Kind.REJECTED), change_request__isnull=False)
        .values("actor").order_by()
        .annotate(n=Count("pk"), wait=Avg(ExpressionWrapper(F("created_at") - F("change_request__submitted_at"),
                                                             output_field=DurationField())))
    )
    referrals = Referral.objects.all()
    figures = {
        "submitted": per(events.filter(kind=ReviewEvent.Kind.SUBMITTED), "actor"),
        "approved": per(decided.filter(kind=ReviewEvent.Kind.APPROVED), "change_request__submitted_by"),
        "rejected": per(decided.filter(kind=ReviewEvent.Kind.REJECTED), "change_request__submitted_by"),
        "reviewed": {row["actor"]: row["n"] for row in reviews},
        "review_hours": {row["actor"]: round(row["wait"].total_seconds() / 3600, 1) for row in reviews if row["wait"]},
        "assigned_by": per(recent(referrals.filter(assigned_by__isnull=False), "assigned_at"), "assigned_by"),
        "handed": per(recent(referrals.filter(expert__isnull=False), "assigned_at"), "expert"),
        "done": per(recent(referrals.filter(status=Referral.Status.DONE), "updated_at"), "expert"),
        "open": per(referrals.filter(expert__isnull=False, status__in=(
            Referral.Status.REFERRED, Referral.Status.REVIEWING, Referral.Status.IN_PROGRESS)), "expert"),
        "tech_closed": per(recent(TechRequest.objects.filter(
            status__in=(TechRequest.Status.DONE, TechRequest.Status.REJECTED)), "status_changed_at"), "assignee"),
        "overdue": Counter(person.pk for item in overdue() for person in item.people),
    }

    rows = []
    for person in User.objects.filter(is_staff=True, is_active=True).prefetch_related("groups").order_by("first_name", "last_name"):
        values = [figures[key].get(person.pk) for key, _label in COLUMNS]
        rows.append({"person": person, "role": role_label(person), "values": values})
    return {"columns": [label for _key, label in COLUMNS], "rows": rows}
