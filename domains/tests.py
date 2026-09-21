from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from accounts.roles import SITE_ADMINS_GROUP, ensure_site_admins_group

from .models import Domain

PASSWORD = "S3cure-pass!"


class DomainGroupTests(TestCase):
    def test_creating_domain_creates_its_group_with_permissions(self):
        domain = Domain.objects.create(name="FPGA", slug="fpga")
        self.assertEqual(domain.group.name, "مدیران حوزه FPGA")
        self.assertTrue(domain.group.permissions.filter(codename="view_domain").exists())

    def test_renaming_domain_renames_group(self):
        domain = Domain.objects.create(name="شبکه", slug="network")
        domain.name = "شبکه و امنیت"
        domain.save()
        domain.group.refresh_from_db()
        self.assertEqual(domain.group.name, "مدیران حوزه شبکه و امنیت")

    def test_deleting_domain_deletes_group_and_staff_access(self):
        domain = Domain.objects.create(name="FPGA", slug="fpga")
        user = User.objects.create_user("09121234567", PASSWORD)
        user.groups.add(domain.group)
        group_id = domain.group.pk
        domain.delete()
        user.refresh_from_db()
        self.assertFalse(Group.objects.filter(pk=group_id).exists())
        self.assertFalse(user.is_staff)


class StaffStatusTests(TestCase):
    """is_staff follows group membership automatically."""

    def setUp(self):
        self.domain = Domain.objects.create(name="FPGA", slug="fpga")
        self.user = User.objects.create_user("09121234567", PASSWORD)

    def test_adding_to_group_gives_admin_access(self):
        self.user.groups.add(self.domain.group)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_staff)

    def test_adding_from_group_side_works_too(self):
        self.domain.group.user_set.add(self.user)  # type: ignore[attr-defined]
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_staff)

    def test_removing_last_group_removes_admin_access(self):
        self.user.groups.add(self.domain.group)
        self.user.groups.remove(self.domain.group)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)

    def test_clearing_group_members_removes_admin_access(self):
        self.domain.group.user_set.add(self.user)  # type: ignore[attr-defined]
        self.domain.group.user_set.clear()  # type: ignore[attr-defined]
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)

    def test_superuser_stays_staff(self):
        admin = User.objects.create_superuser("09351234567", PASSWORD)
        admin.groups.add(self.domain.group)
        admin.groups.clear()
        admin.refresh_from_db()
        self.assertTrue(admin.is_staff)


class RolesTests(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.ai = Domain.objects.create(name="هوش مصنوعی", slug="ai")
        self.user = User.objects.create_user("09121234567", PASSWORD)

    def test_site_admins_group_has_all_permissions(self):
        group = Group.objects.get(name=SITE_ADMINS_GROUP)
        self.assertTrue(group.permissions.filter(codename="change_domain").exists())
        self.assertTrue(group.permissions.filter(codename="change_user").exists())

    def test_one_person_can_manage_two_domains(self):
        self.user.groups.add(self.fpga.group, self.ai.group)
        self.assertEqual(set(self.user.managed_domains), {self.fpga, self.ai})
        self.assertFalse(self.user.is_site_admin)

    def test_site_admin_role(self):
        self.user.groups.add(Group.objects.get(name=SITE_ADMINS_GROUP))
        self.assertTrue(self.user.is_site_admin)


class AdminPanelAccessTests(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.ai = Domain.objects.create(name="هوش مصنوعی", slug="ai")
        self.changelist = reverse("admin:domains_domain_changelist")

    def login_with_groups(self, *groups):
        user = User.objects.create_user("09121234567", PASSWORD)
        user.groups.add(*groups)
        self.client.force_login(user)
        return user

    def test_normal_user_cannot_open_admin(self):
        self.client.force_login(User.objects.create_user("09121234567", PASSWORD))
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)  # redirected to admin login

    def test_domain_manager_sees_only_own_domain(self):
        self.login_with_groups(self.fpga.group)
        response = self.client.get(self.changelist)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["cl"].queryset), [self.fpga])

    def test_domain_manager_cannot_edit_domain(self):
        self.login_with_groups(self.fpga.group)
        url = reverse("admin:domains_domain_change", args=[self.fpga.pk])
        response = self.client.post(url, {"name": "X", "slug": "x", "order": 0})
        self.assertEqual(response.status_code, 403)

    def test_site_admin_sees_all_domains(self):
        self.login_with_groups(Group.objects.get(name=SITE_ADMINS_GROUP))
        response = self.client.get(self.changelist)
        self.assertEqual(set(response.context["cl"].queryset), {self.fpga, self.ai})

    def test_site_admin_cannot_make_superuser(self):
        admin = self.login_with_groups(Group.objects.get(name=SITE_ADMINS_GROUP))
        response = self.client.get(reverse("admin:accounts_user_change", args=[admin.pk]))
        self.assertIn("is_superuser", response.context["adminform"].readonly_fields)



class GroupAdminTests(TestCase):
    """Site admins choose domain group permissions in the admin panel."""

    def setUp(self):
        self.domain = Domain.objects.create(name="FPGA", slug="fpga")
        self.site_admins = Group.objects.get(name=SITE_ADMINS_GROUP)
        admin = User.objects.create_user("09121234567", PASSWORD)
        admin.groups.add(self.site_admins)
        self.client.force_login(admin)

    def change_url(self, group):
        return reverse("admin:auth_group_change", args=[group.pk])

    def test_admin_can_set_domain_group_permissions_and_they_stay(self):
        change = Permission.objects.get(codename="change_product")
        response = self.client.post(self.change_url(self.domain.group), {"permissions": [change.pk]})
        self.assertEqual(response.status_code, 302)
        ensure_site_admins_group()  # what runs after every migrate
        self.assertEqual(list(self.domain.group.permissions.all()), [change])

    def test_domain_group_only_offers_content_permissions(self):
        response = self.client.get(self.change_url(self.domain.group))
        choices = response.context["adminform"].form.fields["permissions"].queryset
        self.assertTrue(choices.filter(codename="change_product").exists())
        self.assertFalse(choices.filter(codename="change_user").exists())
        self.assertFalse(choices.filter(codename="change_domain").exists())
        self.assertFalse(choices.filter(codename="change_changerequest").exists())

    def test_domain_group_cannot_get_user_permissions(self):
        change_user = Permission.objects.get(codename="change_user")
        response = self.client.post(self.change_url(self.domain.group), {"permissions": [change_user.pk]})
        self.assertEqual(response.status_code, 200)  # form error, nothing saved
        self.assertFalse(self.domain.group.permissions.filter(codename="change_user").exists())

    def test_system_groups_cannot_be_deleted(self):
        for group in (self.site_admins, self.domain.group):
            with self.subTest(group=group.name):
                response = self.client.post(reverse("admin:auth_group_delete", args=[group.pk]), {"post": "yes"})
                self.assertEqual(response.status_code, 403)
                self.assertTrue(Group.objects.filter(pk=group.pk).exists())

    def test_site_admins_group_permissions_are_read_only(self):
        response = self.client.get(self.change_url(self.site_admins))
        self.assertNotIn("permissions", response.context["adminform"].form.fields)

class DefaultPermissionTests(TestCase):
    """
    A domain manager has one job description, so every domain group should start from the same
    permissions. They drift when someone edits two dozen checkboxes by hand, and a domain that
    quietly lost «ویرایش ارجاع» cannot price its own referrals.
    """

    def setUp(self):
        self.domain = Domain.objects.create(name="هوش مصنوعی", slug="ai")
        self.owner = User.objects.create_superuser("09120000000", PASSWORD, first_name="مالک")
        self.client.force_login(self.owner)

    def test_a_new_domain_group_can_price_its_referrals(self):
        held = {p.codename for p in self.domain.group.permissions.all()}
        self.assertIn("change_referral", held)
        self.assertIn("view_referral", held)
        self.assertIn("view_servicerequest", held)

    def test_the_action_puts_back_what_was_removed(self):
        self.domain.group.permissions.remove(Permission.objects.get(codename="change_referral"))
        self.assertNotIn("change_referral", {p.codename for p in self.domain.group.permissions.all()})

        self.client.post(reverse("admin:auth_group_changelist"), {
            "action": "restore_default_permissions", "_selected_action": [self.domain.group.pk],
        })
        self.assertIn("change_referral", {p.codename for p in self.domain.group.permissions.all()})

    def test_the_action_never_takes_away_what_someone_granted(self):
        extra = Permission.objects.get(codename="view_requestpayment")
        self.domain.group.permissions.add(extra)

        self.client.post(reverse("admin:auth_group_changelist"), {
            "action": "restore_default_permissions", "_selected_action": [self.domain.group.pk],
        })
        self.assertIn(extra, self.domain.group.permissions.all())

    def test_the_action_leaves_a_group_that_is_not_a_domain_alone(self):
        plain = Group.objects.create(name="یک گروه معمولی")
        self.client.post(reverse("admin:auth_group_changelist"), {
            "action": "restore_default_permissions", "_selected_action": [plain.pk],
        })
        self.assertEqual(plain.permissions.count(), 0)


class AdminFormCompletenessTests(TestCase):
    """
    A ModelAdmin with an explicit `fields` list does not complain when a new model field is
    missing from it — the field simply never appears, and the feature behind it looks broken
    while the code is fine. This catches that.
    """

    # Deliberately kept out of their forms: permissions come from groups, and an approval
    # request's target is recorded by the system, not typed in.
    ALLOWED_TO_BE_HIDDEN = {
        ("accounts", "user"): {"user_permissions"},
        ("approvals", "changerequest"): {"content_type", "object_id", "object_repr", "data"},
    }

    def test_every_editable_field_is_reachable_in_the_admin(self):
        from django.contrib import admin

        missing = []
        for model, model_admin in admin.site._registry.items():
            declared = model_admin.fields
            if not declared and model_admin.fieldsets:
                declared = sum([list(options["fields"]) for _name, options in model_admin.fieldsets], [])
            if not declared:
                continue  # no explicit list: Django shows everything

            shown = set()
            for entry in declared:
                shown.update(entry if isinstance(entry, (tuple, list)) else [entry])
            shown.update(model_admin.readonly_fields or ())
            allowed = self.ALLOWED_TO_BE_HIDDEN.get((model._meta.app_label, model._meta.model_name), set())

            for field in model._meta.get_fields():
                if getattr(field, "editable", False) and not field.auto_created:
                    if field.name not in shown and field.name not in allowed:
                        missing.append(f"{model._meta.label}.{field.name}")

        self.assertEqual(missing, [], f"این فیلدها در پنل دیده نمی‌شوند: {missing}")
