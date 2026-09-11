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
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.db import models, transaction
from django.utils import timezone

from .models import ChangeRequest

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


def save_pending_file(uploaded):
    """New files are stored under pending/ until the change is approved."""
    extension = os.path.splitext(uploaded.name)[1].lower()
    return default_storage.save(f"{PENDING_FILES_DIR}/{uuid.uuid4().hex}{extension}", uploaded)


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
                changes[name] = save_pending_file(value)
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


def delete_pending_files(data):
    for value in data.values():
        if isinstance(value, str) and value.startswith(f"{PENDING_FILES_DIR}/"):
            default_storage.delete(value)


# --- Requests ---------------------------------------------------------------------

def pending_request(obj, action):
    return ChangeRequest.objects.filter(
        content_type__app_label=obj._meta.app_label,
        content_type__model=obj._meta.model_name,
        object_id=obj.pk,
        action=action,
        status=ChangeRequest.Status.PENDING,
    ).first()


def submit(obj, action, user, domain=None, data=None):
    """Create the pending request, or refresh the open one of the same kind."""
    from django.contrib.contenttypes.models import ContentType

    request = pending_request(obj, action)
    if request is None:
        request = ChangeRequest(content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk, action=action)
    elif request.data != (data or {}):
        delete_pending_files({k: v for k, v in request.data.items() if (data or {}).get(k) != v})

    request.object_repr = str(obj)[:200]
    request.domain = domain
    request.data = data or {}
    request.submitted_by = user
    request.submitted_at = timezone.now()
    request.save()
    return request


def withdraw(obj, action):
    """Remove an open request (e.g. the manager undid all their edits)."""
    request = pending_request(obj, action)
    if request is not None:
        delete_pending_files(request.data)
        request.delete()


@transaction.atomic
def approve(request, reviewer, note=""):
    obj = request.target
    if request.action == ChangeRequest.Action.CREATE:
        obj.is_published = True
        obj.save(update_fields=["is_published"])
    elif request.action == ChangeRequest.Action.UPDATE:
        apply_changes(obj, request.data)
    elif request.action == ChangeRequest.Action.ARCHIVE:
        obj.is_archived = True
        obj.save(update_fields=["is_archived"])
    _close(request, ChangeRequest.Status.APPROVED, reviewer, note)


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

def reject(request, reviewer, note=""):
    delete_pending_files(request.data)
    _close(request, ChangeRequest.Status.REJECTED, reviewer, note)


def _close(request, status, reviewer, note):
    request.status = status
    request.reviewed_by = reviewer
    request.reviewed_at = timezone.now()
    request.review_note = note or request.review_note
    request.save()