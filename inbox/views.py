"""
The کارپوشه pages. They live under /admin/ and wear the admin's own chrome, but none of them is
a normal admin view: each one starts from services.visible_messages() so that a visitor only
ever reaches what they sent or received.
"""
import os

from django.contrib import messages as django_messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .forms import ComposeForm
from .models import Delivery, Message, MessageFile

VIEWS = {
    "unread": "نخوانده",
    "all": "همه",
    "archived": "بایگانی",
}


def _guard(request):
    """Every page starts here: a customer has no کارپوشه at all."""
    if not services.has_inbox(request.user):
        raise Http404


def _page(request, template, context):
    return render(request, template, {
        **context,
        "unread_count": services.unread_count(request.user),
        "views": VIEWS,
    })


def inbox(request):
    _guard(request)
    chosen = request.GET.get("view", "unread")
    if chosen not in VIEWS:
        chosen = "unread"

    deliveries = services.received(request.user, archived=(chosen == "archived"))
    if chosen == "unread":
        deliveries = deliveries.filter(read_at__isnull=True)

    return _page(request, "inbox/list.html", {
        "title": "کارپوشه",
        "deliveries": deliveries,
        "chosen": chosen,
        "is_sent_box": False,
    })


def sent_box(request):
    _guard(request)
    archived = request.GET.get("view") == "archived"
    return _page(request, "inbox/list.html", {
        "title": "پیام‌های ارسالی",
        "sent_messages": services.sent(request.user, archived=archived),
        "chosen": "archived" if archived else "all",
        "is_sent_box": True,
    })


def message_detail(request, pk):
    _guard(request)
    message = get_object_or_404(services.visible_messages(request.user), pk=pk)

    delivery = Delivery.objects.filter(message=message, user=request.user).first()
    if delivery is not None:
        delivery.mark_read()  # opening it is what marks it read, not listing it

    return _page(request, "inbox/detail.html", {
        "title": message.subject,
        "message": message,
        "delivery": delivery,
        "recipients": message.deliveries.select_related("user").prefetch_related("user__groups"),
        "is_sender": message.sender_id == request.user.pk,
    })


def compose(request, pk=None):
    """New message, or a reply when pk is given."""
    _guard(request)

    parent = None
    initial = {}
    if pk is not None:
        parent = get_object_or_404(services.visible_messages(request.user), pk=pk)
        if parent.sender_id is None or parent.sender_id == request.user.pk:
            raise Http404  # nobody to reply to
        initial = {"subject": f"پاسخ: {parent.subject}"}

    reply_to = parent.sender if parent else None
    if request.method == "POST":
        form = ComposeForm(request.POST, request.FILES, sender=request.user, reply_to=reply_to)
        if form.is_valid():
            message = services.send(
                sender=request.user,
                subject=form.cleaned_data["subject"],
                body=form.cleaned_data["body"],
                recipients=form.recipients,
                parent=parent,
                files=form.cleaned_data.get("files") or (),
            )
            django_messages.success(request, f"پیام برای {len(form.recipients)} نفر فرستاده شد.")
            return redirect(reverse("admin:inbox_message_detail", args=[message.pk]))
    else:
        form = ComposeForm(initial=initial, sender=request.user, reply_to=reply_to)

    return _page(request, "inbox/compose.html", {
        "title": "پاسخ به پیام" if parent else "نوشتن پیام",
        "form": form,
        "parent": parent,
        "reply_to": reply_to,
    })


@require_POST
def archive(request, pk):
    """Hide a message from this person's own view; the other side keeps theirs."""
    _guard(request)
    message = get_object_or_404(services.visible_messages(request.user), pk=pk)
    now = timezone.now()

    delivery = Delivery.objects.filter(message=message, user=request.user).first()
    if delivery is not None:
        delivery.archived_at = None if delivery.archived_at else now
        delivery.save(update_fields=["archived_at"])
    elif message.sender_id == request.user.pk:
        Message.objects.filter(pk=message.pk).update(
            sender_archived_at=None if message.sender_archived_at else now,
        )

    django_messages.info(request, "بایگانی به‌روز شد.")
    return redirect(reverse("admin:inbox_message_changelist"))


def download(request, pk):
    """
    Send an attachment after checking access now, not when the link was made: somebody dropped
    from every group must find their old links dead.
    """
    _guard(request)
    attachment = get_object_or_404(MessageFile, pk=pk)
    if not services.can_read(request.user, attachment.message):
        raise Http404  # don't reveal that the file exists

    return FileResponse(
        attachment.file.open("rb"), as_attachment=True,
        filename=os.path.basename(attachment.file.name),
    )
