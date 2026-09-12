import os

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from .access import can_open
from .models import Attachment, Lesson

# kind in the URL -> (model, file field). "product" is the model's own product (a Product is its own product).
PROTECTED_FIELDS = {
    "video": (Lesson, "video_file"),
    "attachment": (Attachment, "file"),
    "thesis": ("products.Product", "thesis"),
}


@login_required
def protected_file(request, kind, pk):
    """
    Send a paid file after checking access. Files have no public URL, so this is the only way to them.
    (Production: the web server (nginx) will send the file itself via X-Accel-Redirect; the check stays here.)
    """
    if kind not in PROTECTED_FIELDS:
        raise Http404
    model, field_name = PROTECTED_FIELDS[kind]
    if isinstance(model, str):
        model = apps.get_model(model)
    obj = get_object_or_404(model, pk=pk)
    if not can_open(request.user, getattr(obj, "product", obj)):
        raise Http404  # don't reveal that the file exists
    file = getattr(obj, field_name)
    if not file:
        raise Http404
    return FileResponse(file.open("rb"), as_attachment=(kind == "attachment"), filename=os.path.basename(file.name))