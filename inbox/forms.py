from django import forms
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from . import services
from .validators import validate_file_extension, validate_file_size


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


class PeopleField(forms.ModelMultipleChoiceField):
    """
    Colleagues, shown by name and by the roles they hold.

    Never str(user): that falls back to the mobile number when somebody has no name filled in,
    and the کارپوشه is open to every colleague — it must not turn into the staff phone book.
    """

    def label_from_instance(self, user):
        names = [group.name for group in user.groups.all()]
        if user.is_superuser:
            names.insert(0, "مالک سیستم")  # same wording the user admin already shows
        return f"{user.get_full_name() or _('بدون نام')} — {'، '.join(names) or _('بدون نقش')}"


class ComposeForm(forms.Form):
    subject = forms.CharField(label=_("موضوع"), max_length=200)
    body = forms.CharField(label=_("متن پیام"), widget=forms.Textarea(attrs={"rows": 8}))

    to_users = PeopleField(
        label=_("افراد"), queryset=None, required=False,
        widget=forms.SelectMultiple(attrs={"size": 12}),
    )
    to_groups = forms.ModelMultipleChoiceField(
        label=_("گروه‌ها"), queryset=Group.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=_("همه‌ی اعضای گروه، همین حالا، پیام را می‌گیرند."),
    )
    to_everyone = forms.BooleanField(
        label=_("همه‌ی افراد و گروه‌ها"), required=False,
        help_text=_("برای اطلاعیه‌ای که به کل مجموعه مربوط است."),
    )

    files = MultipleFileField(
        label=_("پیوست"), required=False,
        validators=[validate_file_extension, validate_file_size],
    )

    def __init__(self, *args, sender=None, reply_to=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sender = sender
        self.reply_to = reply_to

        if reply_to is not None:
            # A reply has exactly one recipient by definition; asking again would only be a way
            # to get it wrong. To write to anybody else, you write a new message.
            for name in ("to_users", "to_groups", "to_everyone"):
                del self.fields[name]
            return

        self.fields["to_users"].queryset = services.addressable_users(exclude=sender)
        self.fields["to_groups"].queryset = services.addressable_groups()

    def clean(self):
        data = super().clean()
        if self.reply_to is not None:
            self.recipients = [self.reply_to]
            return data

        if not (data.get("to_users") or data.get("to_groups") or data.get("to_everyone")):
            self.add_error("to_users", _("دست‌کم یک گیرنده انتخاب کنید."))
            return data

        self.recipients = services.resolve_recipients(
            users=data.get("to_users") or (),
            groups=data.get("to_groups") or (),
            everyone=data.get("to_everyone", False),
            exclude=self.sender,
        )
        if not self.recipients:
            self.add_error("to_users", _("هیچ گیرنده‌ای پیدا نشد."))
        return data
