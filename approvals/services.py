"""
Approval workflow: how changes are stored while waiting, and what happens on approve / reject.

Models that use approvals need two boolean fields: is_published and is_archived.
- CREATE  (new item)       -> on approve: is_published = True
- UPDATE  (published item) -> the changed field values wait in request.data; on approve they are applied
- ARCHIVE (published item) -> on approve: is_archived = True (removed from the store, buyers keep access)
"""
import datetime
import os
import uuid
from decimal import Decimal

from django.core.exceptions import FieldDoesNotExist
from django.core.files.uploadedfile import UploadedFile
from django.db import models, transaction
from django.utils import timezone

from .models import ChangeRequest, ReviewEvent

PENDING_FILES_DIR = "pending"


# --- Reading / writing field values as JSON ---------------------------------------

def to_json(field, value):
    if isinstance(field, models.ManyToManyField):
        return sorted(item.pk for item in value)
    if isinstance(field, models.ForeignKey):
        return value.pk if value is not None else None
    if isinstance(field, models.FileField):
        return value.name if value else ""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def current_value(obj, field):
    if isinstance(field, models.ManyToManyField):
        return sorted(getattr(obj, field.name).values_list("pk", flat=True))
    return to_json(field, getattr(obj, field.name))


def save_pending_file(field, uploaded):
    """
    New files wait under pending/ until the change is approved.
    They are saved in the field's own storage, so a paid video never lands in the public media folder.
    """
    extension = os.path.splitext(uploaded.name)[1].lower()
    return field.storage.save(f"{PENDING_FILES_DIR}/{uuid.uuid4().hex}{extension}", uploaded)


def form_changes(form, live):
    """Compare a valid form with the live (database) object and return {field: new value} for real changes."""
    changes = {}
    for name, value in form.cleaned_data.items():
        try:
            field = live._meta.get_field(name)
        except FieldDoesNotExist:
            continue

        if isinstance(field, models.FileField):
            if isinstance(value, UploadedFile):
                changes[name] = save_pending_file(field, value)
            elif value is False and getattr(live, name):  # "clear" checkbox
                changes[name] = ""
            continue

        new = sorted(item.pk for item in value) if isinstance(field, models.ManyToManyField) else to_json(field, value)
        if new != current_value(live, field):
            changes[name] = new
    return changes


def apply_changes(obj, data):
    """Write stored values onto the object, validate and save. Raises ValidationError if no longer valid."""
    many_to_many = {}
    for name, value in data.items():
        field = obj._meta.get_field(name)
        if isinstance(field, models.ManyToManyField):
            many_to_many[name] = value
        elif isinstance(field, models.ForeignKey):
            setattr(obj, field.attname, value)
        elif isinstance(field, models.FileField):
            setattr(obj, name, value or None)
        else:
            setattr(obj, name, field.to_python(value))

    obj.full_clean()
    obj.save()
    for name, ids in many_to_many.items():
        getattr(obj, name).set(ids)


def delete_pending_files(model, data):
    for name, value in data.items():
        if isinstance(value, str) and value.startswith(f"{PENDING_FILES_DIR}/"):
            field = model._meta.get_field(name)
            if isinstance(field, models.FileField):
                field.storage.delete(value)


# --- Requests ---------------------------------------------------------------------

def pending_request(obj, action):
    return ChangeRequest.objects.filter(
        content_type__app_label=obj._meta.app_label,
        content_type__model=obj._meta.model_name,
        object_id=obj.pk,
        action=action,
        status=ChangeRequest.Status.PENDING,
    ).first()


def stage_for(user, domain):
    """
    Where a request from this person starts. The domain's managers look first, unless there is
    nobody to look (a domain with no manager yet) or the person is one of the reviewers already.
    """
    from accounts.roles import is_site_admin
    from domains.access import has_managers, is_manager

    if domain is None or is_site_admin(user) or is_manager(user, domain) or not has_managers(domain):
        return ChangeRequest.Stage.ADMIN
    return ChangeRequest.Stage.DOMAIN


def submit(obj, action, user, domain=None, data=None):
    """
    Create the pending request, or refresh the open one of the same kind.

    A domain manager correcting an expert's work that is waiting on their own desk is not sending
    it anywhere: the request keeps its author and its place, and the correction is recorded as an
    edit. Anyone else saving is (re)sending it, so it starts again from the right desk.
    """
    from django.contrib.contenttypes.models import ContentType
    from domains.access import is_manager

    request = pending_request(obj, action)
    is_new = request is None
    if is_new:
        request = ChangeRequest(content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk, action=action)
    elif request.data != (data or {}):
        delete_pending_files(type(obj), {k: v for k, v in request.data.items() if (data or {}).get(k) != v})

    correcting = (
        not is_new and request.stage == ChangeRequest.Stage.DOMAIN
        and request.submitted_by_id not in (None, user.pk)
        and domain is not None and is_manager(user, domain)
    )
    request.object_repr = str(obj)[:200]
    request.domain = domain
    request.data = data or {}
    if not correcting:
        stage = stage_for(user, domain)
        if is_new or stage != request.stage:
            request.stage_since = timezone.now()
        request.stage = stage
        request.submitted_by = user
        request.submitted_at = timezone.now()
    request.save()
    if is_new:
        record(obj, ReviewEvent.Kind.SUBMITTED, user, request=request)
    return request


def forward(request, manager, note=""):
    """
    A domain manager agrees with an expert's work and sends it to the site admins. A new course
    or project takes its waiting sections, lessons and files along, as approving does.
    """
    request.stage = ChangeRequest.Stage.ADMIN
    request.stage_since = timezone.now()
    request.save(update_fields=["stage", "stage_since"])
    record(request.target, ReviewEvent.Kind.FORWARDED, manager, note, request=request)
    for child in getattr(request.target, "approval_children", list)():
        child_request = pending_request(child, ChangeRequest.Action.CREATE)
        if child_request is not None and child_request.stage == ChangeRequest.Stage.DOMAIN:
            forward(child_request, manager, "همراه با مورد بالاتر ارسال شد.")


def record(obj, kind, actor, note="", changes=(), request=None):
    """Add a step to the item's history (see ReviewEvent)."""
    from django.contrib.contenttypes.models import ContentType

    return ReviewEvent.objects.create(
        content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk, change_request=request,
        kind=kind, actor=actor, note=note, changes=list(changes),
    )


def describe(field, value):
    """A field's value as short plain text, for the history of a manager's corrections."""
    if isinstance(field, models.BooleanField):
        return "بله" if value else "خیر"
    if value in (None, "") or (isinstance(field, models.FileField) and not value):
        return "—"
    if isinstance(field, models.ManyToManyField):
        return "، ".join(str(item) for item in value) or "—"
    if isinstance(field, models.FileField):
        return os.path.basename(getattr(value, "name", str(value))) or "—"
    if field.choices:
        return str(dict(field.flatchoices).get(value, value))
    text = str(value)
    return text if len(text) <= 300 else f"{text[:300]}…"


def withdraw(obj, action):
    """Remove an open request (e.g. the manager undid all their edits)."""
    request = pending_request(obj, action)
    if request is not None:
        delete_pending_files(type(obj), request.data)
        request.delete()


@transaction.atomic
def approve(request, reviewer, note=""):
    obj = request.target
    if request.action == ChangeRequest.Action.CREATE:
        obj.is_published = True
        obj.full_clean()  # e.g. a product without a cover can't be published
        obj.save(update_fields=["is_published"])
        approve_waiting_children(obj, reviewer)
    elif request.action == ChangeRequest.Action.UPDATE:
        apply_changes(obj, request.data)
    elif request.action == ChangeRequest.Action.ARCHIVE:
        obj.is_archived = True
        obj.save(update_fields=["is_archived"])
    _close(request, ChangeRequest.Status.APPROVED, reviewer, note)
    record(obj, ReviewEvent.Kind.APPROVED, reviewer, note, request=request)


def close_answered_requests(obj, reviewer):
    """A site admin published / archived the item directly: the matching open request is answered."""
    answered = []
    if obj.is_published:
        answered.append(ChangeRequest.Action.CREATE)
    if obj.is_archived:
        answered.append(ChangeRequest.Action.ARCHIVE)
    for action in answered:
        request = pending_request(obj, action)
        if request is not None:
            _close(request, ChangeRequest.Status.APPROVED, reviewer, "مستقیم توسط مدیر کل انجام شد.")


def approve_waiting_children(obj, reviewer):
    """
    Publishing a new product also publishes the new sections / lessons / files inside it
    (the admin reviewed the whole thing at once, no need to approve every piece separately).
    """
    for child in getattr(obj, "approval_children", list)():
        child_request = pending_request(child, ChangeRequest.Action.CREATE)
        if child_request is not None:
            approve(child_request, reviewer, "همراه با مورد بالاتر تأیید شد.")


def reject(request, reviewer, note=""):
    """
    Turn the request down and tell the people it concerns straight away: the author always, and
    when the site admins turn down something a domain manager had sent on, that domain's managers.
    """
    model = request.content_type.model_class()
    if model is not None:
        delete_pending_files(model, request.data)
    at_admin_desk = request.stage == ChangeRequest.Stage.ADMIN
    _close(request, ChangeRequest.Status.REJECTED, reviewer, note)
    target = request.target
    if target is not None:
        record(target, ReviewEvent.Kind.REJECTED, reviewer, note, request=request)
    _tell_about_rejection(request, reviewer, note, at_admin_desk)


def _tell_about_rejection(request, reviewer, note, at_admin_desk):
    from inbox import services as inbox

    people = {request.submitted_by} if request.submitted_by else set()
    if at_admin_desk and request.domain is not None:
        people |= set(request.domain.managers_group.user_set.filter(is_active=True))
    people.discard(reviewer)
    if not people:
        return
    who = reviewer.get_full_name() or "بررسی‌کننده"
    lines = [
        f"«{request.object_repr}» ({request.get_action_display()}) توسط {who} رد شد.",
        f"دلیل: {note}" if note else "دلیلی نوشته نشده است.",
    ]
    url = admin_url(request)
    if url:
        lines.append(f"برای دیدن و اصلاح: {url}")
    inbox.send(None, f"رد شد: {request.object_repr}"[:200], "\n".join(lines), sorted(people, key=lambda u: u.pk))


def admin_url(request):
    from django.urls import NoReverseMatch, reverse

    try:
        return reverse(f"admin:{request.content_type.app_label}_{request.content_type.model}_change",
                       args=[request.object_id])
    except NoReverseMatch:
        return ""


def _close(request, status, reviewer, note):
    request.status = status
    request.reviewed_by = reviewer
    request.reviewed_at = timezone.now()
    request.review_note = note or request.review_note
    request.save()