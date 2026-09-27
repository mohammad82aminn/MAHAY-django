from django.contrib.admin.views.decorators import staff_member_required
from django.db import models
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from accounts.roles import is_site_admin
from domains.access import is_member

from .models import ChangeRequest
from .services import PENDING_FILES_DIR


@staff_member_required
def pending_file(request, pk, field_name):
    """Let the reviewers (site admins, and the request's domain people) open a file waiting for approval."""
    change_request = get_object_or_404(ChangeRequest, pk=pk)
    in_domain = change_request.domain is not None and is_member(request.user, change_request.domain)
    if not (is_site_admin(request.user) or in_domain):
        raise Http404

    model = change_request.content_type.model_class()
    name = change_request.data.get(field_name)
    if model is None or not isinstance(name, str) or not name.startswith(f"{PENDING_FILES_DIR}/"):
        raise Http404
    field = model._meta.get_field(field_name)
    if not isinstance(field, models.FileField):
        raise Http404
    return FileResponse(field.storage.open(name, "rb"))