import os

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db.models import Prefetch
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from products.models import Product

from . import progress as progress_service
from .access import can_open, can_open_item, is_open_sample
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


def protected_file(request, kind, pk):
    """
    Send a paid file after checking access. Files have no public URL, so this is the only way to them.
    The one thing open without logging in is the video of a sample lesson (is_open_sample).
    (Production: the web server (nginx) will send the file itself via X-Accel-Redirect; the check stays here.)
    """
    if kind not in PROTECTED_FIELDS:
        raise Http404
    model, field_name = PROTECTED_FIELDS[kind]
    if isinstance(model, str):
        model = apps.get_model(model)
    obj = model._default_manager.filter(pk=pk).first()
    allowed = obj is not None and (
        can_open_item(request.user, obj) or (kind == "video" and is_open_sample(obj))
    )
    if not allowed:
        if not request.user.is_authenticated:
            # Asked to log in whether the file exists or not, so this tells a visitor nothing
            return redirect_to_login(request.get_full_path())
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


def sample_lesson(request, slug, pk):
    """
    A lesson open to everyone, logged in or not: its video and text, the product's other open
    lessons, and the way to buy the rest. Its attachments stay with the buyers.

    The same rule as is_open_sample, asked of the whole product at once: in the store, not free,
    and the lesson ticked and live. Whoever can already open the product is sent to the full lesson
    page instead, where their progress is kept.
    """
    product = get_object_or_404(Product.objects.visible(), slug=slug)
    if can_open(request.user, product):
        return redirect("content:lesson", slug=slug, pk=pk)
    if product.is_free:
        raise Http404  # ordered for nothing and opened whole: it has no samples

    samples = list(progress_service.open_samples(product))
    lesson = next((item for item in samples if item.pk == pk), None)
    if lesson is None:
        raise Http404
    index = samples.index(lesson)
    return render(request, "content/sample.html", {
        "product": product,
        "lesson": lesson,
        "previous_sample": samples[index - 1] if index else None,
        "next_sample": samples[index + 1] if index + 1 < len(samples) else None,
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