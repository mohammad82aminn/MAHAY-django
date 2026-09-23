"""
Applying to work with MAHAY.

Applying needs an account, which is what lets the form skip the name and the mobile number and
makes a fake application pointless. Everything after the form happens in the conversation the
applicant asked to have; the site only records where things stand.
"""
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .forms import CollaborationForm
from .models import CollaborationFile
from .validators import MAX_FILES


@login_required
def apply(request):
    """
    The form, or the open application when there already is one.

    An open application can be corrected while nobody has started reading it; once it is being
    reviewed it is frozen, so that what the reviewer reads cannot change underneath them.
    """
    if not services.may_apply(request.user):
        raise Http404  # somebody who already holds a role is already working with us

    existing = services.open_request(request.user)
    if existing is not None and not existing.is_editable:
        messages.info(request, "درخواست شما در حال بررسی است و تا پایان آن قابل ویرایش نیست.")
        return redirect("services:my_requests")

    if request.method == "POST":
        form = CollaborationForm(request.POST, request.FILES, instance=existing)
        if form.is_valid():
            application = form.save(commit=False)
            application.user = request.user
            application.save()
            form.save_m2m()
            for uploaded in form.cleaned_data.get("files") or ():
                application.files.create(file=uploaded)
            messages.success(request, "درخواست همکاری شما ثبت شد. نتیجه را در «درخواست‌های من» می‌بینید.")
            return redirect("services:my_requests")
    else:
        form = CollaborationForm(instance=existing)

    return render(request, "collaboration/apply.html", {
        "form": form, "existing": existing, "max_files": MAX_FILES,
    })


@login_required
def download(request, pk):
    """
    An attached file, checked at the moment of the download rather than when the link was made,
    so losing the right to read it takes the old link with it.
    """
    item = get_object_or_404(CollaborationFile.objects.select_related("request"), pk=pk)
    if not services.can_read_files(request.user, item.request):
        raise Http404  # don't reveal that the file exists

    return FileResponse(
        item.file.open("rb"), as_attachment=True, filename=os.path.basename(item.file.name),
    )
