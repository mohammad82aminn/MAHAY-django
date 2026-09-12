from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import CreateView, DetailView

from accounts.models import User

from .forms import ContactForm
from .models import Page


class PageDetailView(DetailView):
    template_name = "pages/detail.html"
    context_object_name = "page"

    def get_object(self, queryset=None):
        return get_object_or_404(Page, slug=self.kwargs["slug"], is_published=True)


class ContactView(CreateView):
    form_class = ContactForm
    template_name = "pages/contact.html"

    def get_initial(self):
        user = User.objects.filter(pk=self.request.user.pk).first()
        if user is None:
            return {}
        return {"name": user.get_full_name(), "mobile_number": user.mobile_number, "email": user.email or ""}

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "پیام شما ثبت شد. به‌زودی پاسخ می‌دهیم.")
        return redirect("pages:contact")