"""
What everybody has earned, been paid and is still owed — worked out, never stored, so it can't drift
from the shares and payouts it comes from. Each figure is one grouped query however big the ledger is.
"""
from datetime import timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Payout, Receipt, Share

LIVE = {"receipt__voided_at__isnull": True}

PERIODS = {
    "30": (30, "۳۰ روز اخیر"),
    "90": (90, "۳ ماه اخیر"),
    "365": (365, "یک سال اخیر"),
    "all": (None, "از ابتدا"),
}
DEFAULT_PERIOD = "90"


def people(person_ids=None):
    """[{person, earned, paid, owed}] for everyone with a share or a payout, largest balance first."""
    from accounts.models import User

    earned_q = Share.objects.filter(person__isnull=False, **LIVE)
    paid_q = Payout.objects.filter(person__isnull=False)
    if person_ids is not None:
        earned_q, paid_q = earned_q.filter(person__in=person_ids), paid_q.filter(person__in=person_ids)
    earned = dict(earned_q.values_list("person").annotate(total=Sum("amount")).order_by())
    paid = dict(paid_q.values_list("person").annotate(total=Sum("amount")).order_by())
    users = User.objects.in_bulk(set(earned) | set(paid))
    rows = [
        {"person": users[pk], "earned": earned.get(pk, 0), "paid": paid.get(pk, 0),
         "owed": earned.get(pk, 0) - paid.get(pk, 0)}
        for pk in users
    ]
    return sorted(rows, key=lambda row: -row["owed"])


def funds(domain_ids=None):
    """[{domain, earned, paid, owed}] for every domain's fund."""
    from domains.models import Domain

    earned_q = Share.objects.filter(role=Share.Role.FUND, **LIVE)
    paid_q = Payout.objects.filter(fund__isnull=False)
    if domain_ids is not None:
        earned_q, paid_q = earned_q.filter(domain__in=domain_ids), paid_q.filter(fund__in=domain_ids)
    earned = dict(earned_q.values_list("domain").annotate(total=Sum("amount")).order_by())
    paid = dict(paid_q.values_list("fund").annotate(total=Sum("amount")).order_by())
    domains = Domain.objects.in_bulk(set(earned) | set(paid))
    return [
        {"domain": domains[pk], "earned": earned.get(pk, 0), "paid": paid.get(pk, 0),
         "owed": earned.get(pk, 0) - paid.get(pk, 0)}
        for pk in sorted(domains, key=lambda pk: domains[pk].name)
    ]


def income(period):
    """Money in over the period: in total, month by month, by where it came from, and by domain."""
    days = PERIODS[period][0]
    receipts = Receipt.objects.filter(voided_at__isnull=True)
    shares = Share.objects.filter(**LIVE)
    if days:
        since = timezone.now() - timedelta(days=days)
        receipts, shares = receipts.filter(received_at__gte=since), shares.filter(receipt__received_at__gte=since)

    totals = receipts.aggregate(total=Sum("amount"), count=Count("id"))
    unsplit = receipts.filter(split_at__isnull=True).aggregate(total=Sum("amount"), count=Count("id"))
    by_month = (
        receipts.annotate(month=TruncMonth("received_at")).values("month")
        .annotate(total=Sum("amount"), count=Count("id")).order_by("-month")
    )
    by_source = {row["source"]: row["total"] for row in receipts.values("source").annotate(total=Sum("amount")).order_by()}
    by_domain = (
        shares.values("domain__name").annotate(total=Sum("amount")).order_by("-total")
    )
    company = shares.filter(role=Share.Role.COMPANY).aggregate(total=Sum("amount"))["total"] or 0
    return {
        "total": totals["total"] or 0, "count": totals["count"],
        "unsplit_total": unsplit["total"] or 0, "unsplit_count": unsplit["count"],
        "by_month": list(by_month),
        "by_source": [(label, by_source.get(value, 0)) for value, label in Receipt.Source.choices],
        "by_domain": list(by_domain),
        "company": company,
    }
