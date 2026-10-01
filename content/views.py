import os

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from products.models import Product

from . import progress as progress_service
from .access import can_open, can_open_item
from .models import Attachment, Lesson, LessonProgress, ProductFile, Section

# kind in the URL -> (model, file field). A Product is its own product, hence the getattr below.
PROTECTED_FIELDS = {
    "video": (Lesson, "video_file"),
    "attachment": (Attachment, "file"),
    "product_file": (ProductFile, "file"),
    "thesis": ("products.Product", "thesis"),
}
# Always handed over as a download, never opened in the page: a file someone uploaded must not
# get to run as a web page on this site (an .html or .svg would)
DOWNLOADED = {"attachment", "product_file"}


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
    if not can_open_item(request.user, obj):
        raise Http404  # don't reveal that the file exists (or that a draft does)
    file = getattr(obj, field_name)
    if not file:
        raise Http404
    return FileResponse(file.open("rb"), as_attachment=(kind in DOWNLOADED), filename=os.path.basename(file.name))


# --- Learning pages -------------------------------------------------------------

def get_learnable_product(request, slug):
    """
    The product, if this user may open its content. Otherwise: back to the product page, when there
    is one to go back to; a product that isn't in the store gets 404, like its own page, so this
    address can't be used to find out which unpublished products exist.
    """
    product = get_object_or_404(Product, slug=slug)
    if not can_open(request.user, product):
        if not Product.objects.visible().filter(pk=product.pk).exists():
            raise Http404
        return product, redirect(product.get_absolute_url())
    return product, None


@login_required
def learn(request, slug):
    """Table of contents of a bought product, with the user's progress."""
    product, denied = get_learnable_product(request, slug)
    if denied:
        return denied

    visible = progress_service.published_lessons(product)
    sections = (
        Section.objects.filter(product=product, is_published=True, is_archived=False)
        .prefetch_related(Prefetch("lessons", queryset=visible, to_attr="visible_lessons"))
    )
    return render(request, "content/learn.html", {
        "product": product,
        "sections": sections,
        "companion_files": ProductFile.objects.filter(product=product, is_published=True, is_archived=False),
        **progress_service.summary(request.user, product),
    })


@login_required
def lesson_view(request, slug, pk):
    """One lesson: video, text and files. Saves that the user opened it."""
    product, denied = get_learnable_product(request, slug)
    if denied:
        return denied

    lessons = progress_service.summary(request.user, product)["lessons"]
    lesson = next((item for item in lessons if item.pk == pk), None)
    if lesson is None:
        raise Http404

    row, _ = LessonProgress.objects.get_or_create(user=request.user, lesson=lesson)
    if not lesson.video_file and not row.is_completed:
        row.is_completed = True  # nothing to watch here (text / Aparat lesson): opening it is enough
        row.save(update_fields=["is_completed"])

    index = lessons.index(lesson)
    return render(request, "content/lesson.html", {
        "product": product,
        "lesson": lesson,
        "lesson_progress": row,
        "attachments": Attachment.objects.filter(lesson=lesson, is_published=True, is_archived=False),
        "previous_lesson": lessons[index - 1] if index else None,
        "next_lesson": lessons[index + 1] if index + 1 < len(lessons) else None,
        "position": row.position_seconds,
    })


@login_required
@require_POST
def save_progress(request, pk):
    """Called by the player every few seconds. Returns the new percent."""
    lesson = get_object_or_404(Lesson.objects.select_related("section__product"), pk=pk)
    if not can_open_item(request.user, lesson):
        raise Http404

    try:
        position = float(request.POST.get("position", 0))
        duration = float(request.POST.get("duration", 0))
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid"}, status=400)

    row, _ = LessonProgress.objects.get_or_create(user=request.user, lesson=lesson)
    row.watched(position, duration)
    return JsonResponse({"percent": row.percent, "completed": row.is_completed})