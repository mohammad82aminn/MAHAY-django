"""
What brings people in: the answers to «از کجا با ما آشنا شدید؟» on project orders, consultations
and collaboration applications, counted side by side. Four queries whatever the numbers.
"""
from datetime import timedelta

from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from accounts.heard_from import HeardFrom
from collaboration.models import CollaborationRequest

from .models import ServiceRequest

# ?period=... -> (days back, label); None means since the beginning
PERIODS = {
    "30": (30, "۳۰ روز اخیر"),
    "90": (90, "۳ ماه اخیر"),
    "365": (365, "یک سال اخیر"),
    "all": (None, "از ابتدا"),
}
DEFAULT_PERIOD = "90"
OTHER_ANSWERS_SHOWN = 30
NO_ANSWER = ""  # requests from before the question existed, or typed in by an admin


def build(period):
    days = PERIODS[period][0]
    since = timezone.now() - timedelta(days=days) if days else None
    services = ServiceRequest.objects.all()
    applications = CollaborationRequest.objects.all()
    if since:
        services = services.filter(created_at__gte=since)
        applications = applications.filter(created_at__gte=since)

    counts = {}  # (answer, column) -> number
    for row in services.values("heard_from", "kind").annotate(n=Count("id")).order_by():
        counts[row["heard_from"], row["kind"]] = row["n"]
    for row in applications.values("heard_from").annotate(n=Count("id")).order_by():
        counts[row["heard_from"], "collaboration"] = row["n"]

    columns = [ServiceRequest.Kind.PROJECT, ServiceRequest.Kind.CONSULTING, "collaboration"]
    rows = []
    for value, label in [*HeardFrom.choices, (NO_ANSWER, "بدون پاسخ")]:
        cells = [counts.get((value, column), 0) for column in columns]
        rows.append({"label": label, "cells": cells, "total": sum(cells), "is_answer": value != NO_ANSWER})

    answered = sum(row["total"] for row in rows if row["is_answer"])
    for row in rows:
        row["percent"] = round(row["total"] * 100 / answered) if answered and row["is_answer"] else None
    rows.sort(key=lambda row: (not row["is_answer"], -row["total"]))  # the biggest first, «بدون پاسخ» last

    return {
        "rows": rows,
        "column_totals": [sum(row["cells"][i] for row in rows) for i in range(len(columns))],
        "grand_total": sum(row["total"] for row in rows),
        "answered": answered,
        "other_answers": _other_answers(services, applications),
    }


def _other_answers(services, applications):
    """What people wrote under «سایر», newest first: the place to spot a channel worth its own option."""
    wanted = {"heard_from": HeardFrom.OTHER}
    found = [
        {"text": item.heard_from_other, "where": item.get_kind_display(), "at": item.created_at,
         "url": reverse("admin:services_servicerequest_change", args=[item.pk])}
        for item in services.filter(**wanted).only("heard_from_other", "kind", "created_at")
        .order_by("-created_at")[:OTHER_ANSWERS_SHOWN]
    ] + [
        {"text": item.heard_from_other, "where": "همکاری با ما", "at": item.created_at,
         "url": reverse("admin:collaboration_collaborationrequest_change", args=[item.pk])}
        for item in applications.filter(**wanted).only("heard_from_other", "created_at")
        .order_by("-created_at")[:OTHER_ANSWERS_SHOWN]
    ]
    found.sort(key=lambda item: item["at"], reverse=True)
    return found[:OTHER_ANSWERS_SHOWN]
