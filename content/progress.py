"""Course progress: which lessons a user finished and how far they are."""
from .models import Lesson, LessonProgress


def published_lessons(product):
    return Lesson.objects.filter(
        section__product=product, section__is_published=True, section__is_archived=False,
        is_published=True, is_archived=False,
    )


def open_samples(product):
    """
    The lessons of this product anyone may watch (content.access.is_open_sample), in course order.
    The product's own side of that rule, in the store and not free, is the caller's to check.
    """
    return (
        published_lessons(product).filter(is_free_preview=True).select_related("section")
        .order_by("section__order", "section__id", "order", "id")
    )


def progress_map(user, product):
    """{lesson_id: LessonProgress} for this product (one query)."""
    if not user.is_authenticated:
        return {}
    rows = LessonProgress.objects.filter(user=user, lesson__in=published_lessons(product))
    return {lesson_pk: row for lesson_pk, row in ((row.lesson.pk, row) for row in rows.select_related("lesson"))}


def summary(user, product):
    """Overall progress of a product: total lessons, finished ones, percent and where to continue."""
    lessons = list(published_lessons(product).select_related("section").order_by("section__order", "section__id", "order", "id"))
    done = progress_map(user, product)
    completed = [lesson for lesson in lessons if lesson.pk in done and done[lesson.pk].is_completed]

    next_lesson = next((lesson for lesson in lessons if not (lesson.pk in done and done[lesson.pk].is_completed)), None)
    return {
        "lessons": lessons,
        "progress": done,
        "total": len(lessons),
        "completed": len(completed),
        "percent": round(len(completed) * 100 / len(lessons)) if lessons else 0,
        "next_lesson": next_lesson or (lessons[0] if lessons else None),
    }