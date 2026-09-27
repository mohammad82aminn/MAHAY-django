"""
Who sees and who works on technical requests, and who hears about what.

- Anyone on the staff files requests and follows their own.
- The technical admins and the site admins see all of them and work on them.
- The office managers see all of them too, read-only, to follow how quickly they are handled.
"""
from django.urls import reverse

from accounts.models import User
from accounts.roles import TECH_ADMINS_GROUP, is_office_manager, is_site_admin, is_tech_admin

from .models import TechRequest


def works_on_requests(user):
    return is_site_admin(user) or is_tech_admin(user)


def sees_all_requests(user):
    return works_on_requests(user) or is_office_manager(user)


def visible_requests(user):
    if sees_all_requests(user):
        return TechRequest.objects.all()
    return TechRequest.objects.filter(requester=user)


def tech_team():
    return list(User.objects.filter(groups__name=TECH_ADMINS_GROUP, is_active=True).distinct())


def _send(people, subject, lines):
    from inbox import services as inbox

    people = [person for person in people if person is not None and person.is_active]
    if people:
        inbox.send(None, subject[:200], "\n".join(lines), people)


def url_of(request):
    return reverse("admin:support_techrequest_change", args=[request.pk])


def announce_new(request):
    """A new request: the technical team hears at once, the urgent ones marked as such."""
    urgent = "فوری — " if request.priority == TechRequest.Priority.URGENT else ""
    _send(tech_team(), f"{urgent}درخواست فنی تازه: {request.title}", [
        f"{request.get_kind_display()} از {request.requester.get_full_name() or request.requester.mobile_number}",
        "",
        request.description[:500],
        "",
        url_of(request),
    ])


def announce_status(request, actor):
    """The requester hears when their request moves on, with the note that came with it."""
    if request.requester == actor:
        return
    lines = [f"وضعیت «{request.title}»: {request.get_status_display()}"]
    if request.status_note:
        lines += ["", request.status_note]
    _send([request.requester], f"درخواست فنی شما: {request.get_status_display()}", [*lines, "", url_of(request)])


def announce_message(message):
    """A new word in the conversation reaches the other side: the requester, or the person on it."""
    request = message.request
    if message.author == request.requester:
        people = [request.assignee] if request.assignee else tech_team()
    else:
        people = [request.requester]
    people = [person for person in people if person != message.author]
    _send(people, f"پیام تازه در درخواست فنی: {request.title}", [message.body[:500], "", url_of(request)])
