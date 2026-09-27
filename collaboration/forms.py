from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.heard_from import HeardFromFormMixin
from domains.models import Domain

from .models import CollaborationRequest
from .validators import MAX_FILES, validate_file_extension, validate_file_size

MIN_PITCH = 30  # characters, so an application says something a person can judge


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Several files in one field; Django's own FileField only ever cleans one."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        clean_one = super().clean
        if isinstance(data, (list, tuple)):
            return [clean_one(item, initial) for item in data]
        return [clean_one(data, initial)] if data else []


WORK_FIELDS = {"teach": "can_teach", "build": "can_build", "advise": "can_advise"}


class CollaborationForm(HeardFromFormMixin, forms.ModelForm):
    # One question with three ticks, rather than three separate yes/no fields stacked down the
    # page with their labels adrift from their boxes.
    work = forms.MultipleChoiceField(
        label=_("چه نوع همکاری‌ای؟"), widget=forms.CheckboxSelectMultiple,
        choices=(
            ("teach", _("ساخت دوره آموزشی")),
            ("build", _("انجام پروژه")),
            ("advise", _("مشاوره")),
        ),
        help_text=_("می‌توانید چند مورد را انتخاب کنید."),
        error_messages={"required": _("دست‌کم یک نوع همکاری را انتخاب کنید.")},
    )

    files = MultipleFileField(
        label=_("رزومه و نمونه‌کار"), required=False,
        validators=[validate_file_extension, validate_file_size],
        help_text=_("اختیاری. می‌توانید چند فایل بفرستید."),
    )

    class Meta:
        model = CollaborationRequest
        # Ordered the way a person tells the story: what I want to do, where, who I am, and
        # finally how to reach me.
        fields = (
            "domains", "other_domain", "pitch",
            "degree", "field_of_study", "experience", "skills", "links",
            "contact_channel", "contact_id", "heard_from", "heard_from_other",
        )
        widgets = {
            "contact_id": forms.TextInput(attrs={"dir": "ltr", "placeholder": "@username"}),
            "pitch": forms.Textarea(attrs={"rows": 5}),
            "experience": forms.Textarea(attrs={"rows": 4}),
            "skills": forms.Textarea(attrs={"rows": 3}),
            "links": forms.Textarea(attrs={"rows": 3, "dir": "ltr"}),
            "domains": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["domains"].queryset = Domain.objects.filter(is_active=True)
        self.fields["domains"].required = False
        # Everything but the way to reach them and what they can do is optional on purpose:
        # an application should be quick to send, and the conversation fills in the rest.
        for name in ("degree", "field_of_study", "experience", "skills", "links", "other_domain"):
            self.fields[name].required = False

        if self.instance.pk:
            self.initial["work"] = [
                key for key, field in WORK_FIELDS.items() if getattr(self.instance, field)
            ]

    def save(self, commit=True):
        application = super().save(commit=False)
        chosen = set(self.cleaned_data.get("work") or ())
        for key, field in WORK_FIELDS.items():
            setattr(application, field, key in chosen)
        if commit:
            application.save()
            self.save_m2m()
        return application

    def clean_pitch(self):
        text = self.cleaned_data["pitch"].strip()
        if len(text) < MIN_PITCH:
            raise forms.ValidationError(_("کمی بیشتر بنویسید تا بتوانیم درست قضاوت کنیم."))
        return text

    def clean_files(self):
        files = self.cleaned_data.get("files") or []
        if len(files) > MAX_FILES:
            raise forms.ValidationError(
                _("حداکثر %(limit)d فایل می‌توانید بفرستید."), params={"limit": MAX_FILES},
            )
        return files

    def clean(self):
        data = super().clean()
        channel = data.get("contact_channel")
        if channel and channel != CollaborationRequest.Channel.PHONE and not data.get("contact_id"):
            self.add_error("contact_id", _("آیدی خود را در این بستر بنویسید."))
        return data
