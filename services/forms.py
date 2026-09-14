from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.forms import MOBILE_ATTRS
from accounts.validators import normalize_mobile_number
from domains.models import Domain

from .models import ServiceRequest

MIN_DESCRIPTION = 30  # characters, so we don't get a request that only says "hello"


class ServiceRequestForm(forms.ModelForm):
    class Meta:
        model = ServiceRequest
        fields = (
            "name", "mobile_number", "email", "contact_channel", "contact_id",
            "title", "domains", "other_domain", "level", "need", "description", "deadline", "attachment",
        )
        widgets = {
            "mobile_number": forms.TextInput(attrs=MOBILE_ATTRS),
            "email": forms.EmailInput(attrs={"dir": "ltr"}),
            "contact_id": forms.TextInput(attrs={"dir": "ltr", "placeholder": "@username"}),
            "domains": forms.CheckboxSelectMultiple,
            "description": forms.Textarea(attrs={"rows": 7}),
            "deadline": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {"title": _("عنوان پروژه یا موضوع مشاوره")}

    domains = forms.ModelMultipleChoiceField(
        label=_("حوزه‌ها"), queryset=Domain.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple, help_text=_("می‌توانید چند حوزه را انتخاب کنید."),
    )

    def __init__(self, *args, kind=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.kind = kind
        field = self.fields["domains"]
        if isinstance(field, forms.ModelMultipleChoiceField):
            field.queryset = Domain.objects.filter(is_active=True)
        self.fields["description"].help_text = _(
            "هر چه کامل‌تر بنویسید، سریع‌تر و دقیق‌تر راهنمایی می‌شوید: هدف کار، امکانات موجود، "
            "محدودیت‌ها و کارهایی که تا حالا انجام داده‌اید."
        )

    def clean_mobile_number(self):
        return normalize_mobile_number(self.cleaned_data["mobile_number"])

    def clean_description(self):
        text = self.cleaned_data["description"].strip()
        if len(text) < MIN_DESCRIPTION:
            raise forms.ValidationError(_("توضیحات را کامل‌تر بنویسید تا بتوانیم درست راهنمایی کنیم."))
        return text

    def clean(self):
        super().clean()
        data = self.cleaned_data

        if not data.get("domains") and not data.get("other_domain"):
            self.add_error("domains", _("حوزه را انتخاب کنید یا حوزه‌ی خود را در کادر بعدی بنویسید."))

        channel = data.get("contact_channel")
        if channel and channel != ServiceRequest.Channel.PHONE and not data.get("contact_id"):
            self.add_error("contact_id", _("آیدی خود را در این بستر بنویسید."))
        return data

    def save(self, commit=True):
        request_object = super().save(commit=False)
        if self.kind:
            request_object.kind = self.kind
        if commit:
            request_object.save()
            self.save_m2m()
        return request_object