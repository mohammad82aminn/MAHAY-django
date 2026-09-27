"""
«از کجا با ما آشنا شدید؟» — asked on every form a newcomer sends: a project order, a consultation
and a collaboration application. Shown only to site admins, as a report of what brings people in.

Not to be confused with ServiceRequest.source («منبع»): that is how a request reached us (the site
form, or an admin typing in a Telegram message), filled in by an admin; this is what the person
says first brought them here.
"""
from django import forms
from django.db import models
from django.utils.translation import gettext_lazy as _


class HeardFrom(models.TextChoices):
    INSTAGRAM = "instagram", _("اینستاگرام")
    TELEGRAM = "telegram", _("تلگرام")
    APARAT = "aparat", _("آپارات")
    EITAA = "eitaa", _("ایتا")
    RUBIKA = "rubika", _("روبیکا")
    GOOGLE = "google", _("جستجو در گوگل")
    FRIENDS = "friends", _("معرفی دوستان و آشنایان")
    UNIVERSITY = "university", _("استاد یا دانشگاه")
    OTHER = "other", _("سایر")


def heard_from_field():
    # Blank is allowed here, not on the site's forms: older requests never had the question,
    # and a request an admin types in from a phone call may not have the answer.
    return models.CharField(_("نحوه‌ی آشنایی"), max_length=12, choices=HeardFrom.choices, blank=True)


def heard_from_other_field():
    return models.CharField(_("نحوه‌ی آشنایی (سایر)"), max_length=150, blank=True)


class HeardFromFormMixin:
    """Makes the question required on a public form, as one click, with a box for «سایر»."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choice = self.fields["heard_from"]
        choice.label = _("از کجا با ما آشنا شدید؟")
        choice.required = True
        choice.choices = HeardFrom.choices  # no empty «---------» radio
        choice.widget = forms.RadioSelect(choices=HeardFrom.choices)
        choice.error_messages["required"] = _("یکی از گزینه‌ها را انتخاب کنید.")

        other = self.fields["heard_from_other"]
        other.label = _("از کجا؟")
        other.widget.attrs.update({"placeholder": _("لطفاً بنویسید از کجا"), "data-show-when": "heard_from=other"})

    def clean(self):
        data = super().clean()
        if data.get("heard_from") == HeardFrom.OTHER:
            if not (data.get("heard_from_other") or "").strip():
                self.add_error("heard_from_other", _("بنویسید از کجا با ما آشنا شدید."))
        else:
            data["heard_from_other"] = ""  # a leftover from switching choices is not an answer
        return data
