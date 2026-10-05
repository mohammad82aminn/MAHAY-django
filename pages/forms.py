from django import forms
from django.utils.translation import gettext as _

from accounts.forms import MOBILE_ATTRS
from accounts.validators import normalize_mobile_number

from .models import ContactMessage


class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ("name", "mobile_number", "email", "subject", "body")
        widgets = {
            "mobile_number": forms.TextInput(attrs=MOBILE_ATTRS),
            "email": forms.EmailInput(attrs={"dir": "ltr"}),
            "body": forms.Textarea(attrs={"rows": 6}),
        }

    def clean_mobile_number(self):
        number = self.cleaned_data.get("mobile_number", "").strip()
        return normalize_mobile_number(number) if number else ""

    def clean(self):
        super().clean()
        data = self.cleaned_data
        if not data.get("mobile_number") and not data.get("email"):
            raise forms.ValidationError(_("برای پاسخ دادن، شماره تماس یا ایمیل خود را وارد کنید."))
        return data