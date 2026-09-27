"""«درخواست‌های فنی»: anyone on the staff asks, the technical team works on it, everyone hears."""
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from accounts.roles import OFFICE_GROUP, SITE_ADMINS_GROUP, TECH_ADMINS_GROUP
from domains.models import Domain
from inbox.models import Message

from .models import TechRequest, TechRequestFile, TechRequestMessage

PASSWORD = "S3cure-pass!"
TEMP_PROTECTED = tempfile.mkdtemp()


@override_settings(PROTECTED_MEDIA_ROOT=TEMP_PROTECTED)
class SupportTestCase(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.expert = self.person("09123333333", self.fpga.experts_group)
        self.colleague = self.person("09124444444", self.fpga.experts_group)
        self.tech = self.person("09120000001", Group.objects.get(name=TECH_ADMINS_GROUP))
        self.office = self.person("09120000003", Group.objects.get(name=OFFICE_GROUP))
        self.admin = self.person("09120000000", Group.objects.get(name=SITE_ADMINS_GROUP))

    @staticmethod
    def person(number, group):
        user = User.objects.create_user(number, PASSWORD, first_name=f"نفر {number[-2:]}")
        user.groups.add(group)
        user.refresh_from_db()
        return user

    def ask(self, user, **changes):
        self.client.force_login(user)
        data = {
            "kind": "bug", "priority": "urgent", "title": "ویدیو پخش نمی‌شود", "description": "صفحه‌ی درس اول",
            "page_url": "/content/learn/ai/lesson/1/",
            "messages-TOTAL_FORMS": "0", "messages-INITIAL_FORMS": "0",
            "files-TOTAL_FORMS": "1", "files-INITIAL_FORMS": "0",
            "files-0-file": SimpleUploadedFile("shot.png", b"\x89PNG fake", content_type="image/png"),
        }
        data.update(changes)
        self.client.post(reverse("admin:support_techrequest_add"), data)
        return TechRequest.objects.latest("pk")

    def work(self, user, request, **changes):
        self.client.force_login(user)
        data = {
            "status": request.status, "assignee": request.assignee_id or "", "status_note": request.status_note,
            "messages-TOTAL_FORMS": "0", "messages-INITIAL_FORMS": "0",
            "files-TOTAL_FORMS": "0", "files-INITIAL_FORMS": "0",
        }
        data.update(changes)
        return self.client.post(reverse("admin:support_techrequest_change", args=[request.pk]), data)

    def inbox_of(self, user):
        return Message.objects.filter(deliveries__user=user, from_system=True)


class AskingTests(SupportTestCase):
    def test_anyone_on_the_staff_asks_and_the_team_hears_at_once(self):
        request = self.ask(self.expert)
        self.assertEqual((request.requester, request.status), (self.expert, TechRequest.Status.NEW))
        self.assertEqual(TechRequestFile.objects.get().request, request)
        [message] = self.inbox_of(self.tech)
        self.assertIn("فوری", message.subject)

    def test_everyone_sees_their_own_the_team_and_the_office_see_all(self):
        mine = self.ask(self.expert)
        changelist = reverse("admin:support_techrequest_changelist")
        for user, sees in ((self.expert, True), (self.colleague, False), (self.tech, True), (self.office, True),
                           (self.admin, True)):
            with self.subTest(user=user.mobile_number):
                self.client.force_login(user)
                self.assertEqual(mine in self.client.get(changelist).context["cl"].queryset, sees)

    def test_a_screenshot_opens_only_for_those_who_see_the_request(self):
        self.ask(self.expert)
        url = reverse("admin:support_techrequest_file", args=[TechRequestFile.objects.get().pk])
        for user, status in ((self.expert, 200), (self.tech, 200), (self.colleague, 404)):
            with self.subTest(user=user.mobile_number):
                self.client.force_login(user)
                self.assertEqual(self.client.get(url).status_code, status)


class WorkingTests(SupportTestCase):
    def test_the_team_moves_it_on_and_the_requester_hears(self):
        request = self.ask(self.expert)
        self.work(self.tech, request, status="done", assignee=self.tech.pk, status_note="کش مرورگر بود.")
        request.refresh_from_db()
        self.assertEqual((request.status, request.assignee), (TechRequest.Status.DONE, self.tech))
        [message] = self.inbox_of(self.expert)
        self.assertIn("کش مرورگر بود.", message.body)

    def test_the_requester_cannot_mark_it_done(self):
        request = self.ask(self.expert)
        self.work(self.expert, request, status="done", title="تغییر", kind="bug", priority="normal",
                  description="x")
        request.refresh_from_db()
        self.assertEqual(request.status, TechRequest.Status.NEW)

    def test_the_office_follows_along_but_takes_no_part(self):
        request = self.ask(self.expert)
        self.assertEqual(self.work(self.office, request, status="done").status_code, 403)

    def test_the_conversation_reaches_the_other_side(self):
        request = self.ask(self.expert)
        self.work(self.tech, request, status="in_progress", assignee=self.tech.pk, **{
            "messages-TOTAL_FORMS": "1", "messages-0-body": "کدام مرورگر؟",
        })
        self.assertEqual(TechRequestMessage.objects.get().author, self.tech)
        self.assertTrue(self.inbox_of(self.expert).filter(body__contains="کدام مرورگر؟").exists())

    def test_the_red_number_is_for_the_team(self):
        from django.contrib import admin

        from accounts.pending import count_for

        self.ask(self.expert)
        for user, expected in ((self.tech, 1), (self.admin, 1), (self.expert, 0), (self.office, 0)):
            with self.subTest(user=user.mobile_number):
                fake = type("Request", (), {"user": user})()
                self.assertEqual(count_for(TechRequest, fake), expected)
        self.assertTrue(admin.site._registry[TechRequest].counts_for_tech_admins)

    def test_a_request_nobody_picked_up_is_reminded_after_48_hours(self):
        from django.utils import timezone

        from inbox import reminders

        self.ask(self.expert)
        Message.objects.all().delete()
        reminders.send_due(now=timezone.now() + timedelta(hours=49))
        self.assertIn("هنوز برداشته نشده", self.inbox_of(self.tech).get().body)


def tearDownModule():
    shutil.rmtree(TEMP_PROTECTED, ignore_errors=True)
