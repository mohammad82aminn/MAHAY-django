import shutil
import tempfile

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from accounts.roles import SITE_ADMINS_GROUP, TECH_ADMINS_GROUP, is_site_admin
from domains.models import Domain

from . import services, validators
from .models import ContactChannel, Referral, RequestEvent, RequestMessage, RequestPayment, ServiceRequest

PASSWORD = "S3cure-pass!"
TEMP_PROTECTED = tempfile.mkdtemp()
DESCRIPTION = "یک برد FPGA داریم و می‌خواهیم تشخیص خط را رویش پیاده کنیم؛ کد اولیه نوشته شده است."


@override_settings(PROTECTED_MEDIA_ROOT=TEMP_PROTECTED)
class ServiceTestCase(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.ai = Domain.objects.create(name="هوش مصنوعی", slug="ai")

        self.admin = User.objects.create_user("09120000000", PASSWORD, first_name="مدیر")
        self.admin.groups.add(Group.objects.get(name=SITE_ADMINS_GROUP))
        self.tech = User.objects.create_user("09120000001", PASSWORD, first_name="فنی")
        self.tech.groups.add(Group.objects.get(name=TECH_ADMINS_GROUP))
        self.expert = User.objects.create_user("09121111111", PASSWORD, first_name="علی")
        self.expert.groups.add(self.fpga.group)
        self.other_expert = User.objects.create_user("09122222222", PASSWORD, first_name="سارا")
        self.other_expert.groups.add(self.ai.group)

    def form_data(self, **changes):
        data = {
            "name": "رضا محمدی", "mobile_number": "09351234567", "email": "",
            "contact_channel": "telegram", "contact_id": "@reza",
            "title": "ربات تعقیب خط", "domains": [self.fpga.pk], "other_domain": "",
            "level": "university", "need": "full", "description": DESCRIPTION, "deadline": "",
        }
        data.update(changes)
        return data

    def submit(self, url_name="services:project", **changes):
        return self.client.post(reverse(url_name), self.form_data(**changes), follow=True)


class PublicFormTests(ServiceTestCase):
    def test_pages_open_without_login(self):
        for name in ("services:project", "services:consulting"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "ثبت درخواست")

    def test_guest_can_submit_and_gets_a_tracking_code(self):
        response = self.submit()
        item = ServiceRequest.objects.get()
        self.assertEqual(item.kind, "project")
        self.assertEqual(item.status, "new")
        self.assertIsNone(item.user)
        self.assertEqual(item.mobile_number, "+989351234567")  # normalized
        self.assertTrue(item.tracking_code.startswith("PR-"))
        self.assertContains(response, item.tracking_code)
        self.assertContains(response, "راه‌های ارتباطی")
        self.assertEqual(RequestEvent.objects.filter(request=item).count(), 1)

    def test_consulting_code_has_its_own_prefix(self):
        self.submit("services:consulting")
        self.assertTrue(ServiceRequest.objects.get().tracking_code.startswith("CS-"))

    def test_logged_in_request_is_linked_to_the_account(self):
        buyer = User.objects.create_user("09129999999", PASSWORD, first_name="نگار", last_name="ک")
        self.client.force_login(buyer)
        response = self.client.get(reverse("services:project"))
        self.assertEqual(response.context["form"].initial["name"], "نگار ک")
        self.submit()
        self.assertEqual(ServiceRequest.objects.get().user, buyer)

    def test_short_description_is_refused(self):
        response = self.client.post(reverse("services:project"), self.form_data(description="سلام"))
        self.assertContains(response, "کامل‌تر بنویسید")
        self.assertFalse(ServiceRequest.objects.exists())

    def test_a_domain_or_other_domain_is_required(self):
        response = self.client.post(reverse("services:project"), self.form_data(domains=[]))
        self.assertContains(response, "حوزه را انتخاب کنید")
        self.client.post(reverse("services:project"), self.form_data(domains=[], other_domain="رباتیک"))
        self.assertEqual(ServiceRequest.objects.get().other_domain, "رباتیک")

    def test_contact_id_is_required_except_for_phone(self):
        response = self.client.post(reverse("services:project"), self.form_data(contact_id=""))
        self.assertContains(response, "آیدی خود را")
        self.client.post(reverse("services:project"), self.form_data(contact_channel="phone", contact_id=""))
        self.assertTrue(ServiceRequest.objects.exists())

    def test_several_domains_can_be_chosen(self):
        self.submit(domains=[self.fpga.pk, self.ai.pk])
        self.assertEqual(ServiceRequest.objects.get().domains.count(), 2)

    def test_too_many_requests_are_refused(self):
        for _ in range(3):
            self.submit()
        response = self.submit()
        self.assertContains(response, "یک ساعت دیگر")
        self.assertEqual(ServiceRequest.objects.count(), 3)

    def test_a_new_number_every_time_does_not_escape_the_limit(self):
        # The form needs no account, so the number proves nothing: the address has to count too.
        for index in range(services.MAX_PER_IP_PER_HOUR):
            self.submit(mobile_number=f"0935000{index:04d}")
        response = self.submit(mobile_number="09361234567")
        self.assertContains(response, "یک ساعت دیگر")
        self.assertEqual(ServiceRequest.objects.count(), services.MAX_PER_IP_PER_HOUR)

    def test_an_oversized_attachment_is_refused(self):
        big = SimpleUploadedFile("spec.pdf", b"x" * (validators.MAX_ATTACHMENT_MB * 1024 * 1024 + 1))
        response = self.client.post(reverse("services:project"), self.form_data(attachment=big))
        self.assertContains(response, "مگابایت")
        self.assertFalse(ServiceRequest.objects.exists())

    def test_an_unexpected_file_type_is_refused(self):
        script = SimpleUploadedFile("run.exe", b"MZ")
        response = self.client.post(reverse("services:project"), self.form_data(attachment=script))
        self.assertContains(response, "پذیرفته نمی‌شود")
        self.assertFalse(ServiceRequest.objects.exists())

    def test_an_allowed_attachment_still_goes_through(self):
        self.submit(attachment=SimpleUploadedFile("spec.pdf", b"%PDF-1.4"))
        self.assertTrue(ServiceRequest.objects.get().attachment)

    def test_submitted_page_is_not_public(self):
        self.submit()
        code = ServiceRequest.objects.get().tracking_code
        self.client.logout()  # clears the session that proved the submit
        self.assertEqual(self.client.get(reverse("services:submitted", args=[code])).status_code, 404)

    def test_only_active_channels_are_shown(self):
        ContactChannel.objects.create(kind="telegram", label="پشتیبانی", value="@mahay", is_active=True)
        ContactChannel.objects.create(kind="phone", label="تماس", value="02100000000", is_active=False)
        response = self.client.get(reverse("services:project"))
        self.assertContains(response, "@mahay")
        self.assertNotContains(response, "02100000000")

    def test_channel_link_is_built(self):
        channel = ContactChannel.objects.create(kind="telegram", label="پشتیبانی", value="@mahay")
        self.assertEqual(channel.link, "https://t.me/mahay")


class MyRequestsTests(ServiceTestCase):
    def test_user_sees_only_their_own_requests(self):
        user = User.objects.create_user("09129999999", PASSWORD, first_name="نگار")
        mine = ServiceRequest.objects.create(kind="project", name="نگار", mobile_number="+989129999999",
                                             contact_channel="phone", title="مال من", description=DESCRIPTION,
                                             level="thesis", need="full", user=user)
        ServiceRequest.objects.create(kind="project", name="غریبه", mobile_number="+989351234567",
                                      contact_channel="phone", title="مال دیگری", description=DESCRIPTION,
                                      level="thesis", need="full")
        self.client.force_login(user)
        response = self.client.get(reverse("services:my_requests"))
        self.assertContains(response, mine.tracking_code)
        self.assertNotContains(response, "مال دیگری")

    def test_page_needs_login(self):
        url = reverse("services:my_requests")
        self.assertIn(reverse("accounts:login"), self.client.get(url)["Location"])


class AdminWorkflowTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.submit(domains=[self.fpga.pk, self.ai.pk])
        self.item = ServiceRequest.objects.get()

    def change_url(self, obj=None):
        return reverse("admin:services_servicerequest_change", args=[(obj or self.item).pk])

    def test_both_full_access_groups_are_site_admins(self):
        self.assertTrue(is_site_admin(self.admin))
        self.assertTrue(is_site_admin(self.tech))
        self.assertFalse(is_site_admin(self.expert))

    def test_admin_sees_every_request(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:services_servicerequest_changelist"))
        self.assertEqual(list(response.context["cl"].queryset), [self.item])

    def test_expert_sees_nothing_before_a_referral(self):
        self.client.force_login(self.expert)
        response = self.client.get(reverse("admin:services_servicerequest_changelist"))
        self.assertEqual(list(response.context["cl"].queryset), [])

    def test_expert_sees_the_request_after_it_is_referred(self):
        Referral.objects.create(request=self.item, domain=self.fpga, expert=self.expert)
        self.client.force_login(self.expert)
        response = self.client.get(reverse("admin:services_servicerequest_changelist"))
        self.assertEqual(list(response.context["cl"].queryset), [self.item])

        self.client.force_login(self.other_expert)  # a manager of another domain
        response = self.client.get(reverse("admin:services_servicerequest_changelist"))
        self.assertEqual(list(response.context["cl"].queryset), [])

    def test_expert_sees_the_contact_details(self):
        referral = Referral.objects.create(request=self.item, domain=self.fpga, expert=self.expert)
        self.client.force_login(self.expert)
        response = self.client.get(reverse("admin:services_referral_change", args=[referral.pk]))
        self.assertContains(response, "+989351234567")
        self.assertContains(response, "@reza")

    def test_expert_reports_price_and_progress(self):
        referral = Referral.objects.create(request=self.item, domain=self.fpga, expert=self.expert)
        self.client.force_login(self.expert)
        response = self.client.post(reverse("admin:services_referral_change", args=[referral.pk]), {
            "expert": self.expert.pk, "status": "in_progress", "quoted_price": 12_000_000,
            "duration_text": "۳ هفته", "feasibility": "قابل انجام است", "done_work": "بررسی اولیه",
            "remaining_work": "پیاده‌سازی", "attachment": "",
        })
        self.assertEqual(response.status_code, 302)
        referral.refresh_from_db()
        self.assertEqual(referral.quoted_price, 12_000_000)
        self.assertEqual(referral.status, "in_progress")
        self.assertTrue(RequestEvent.objects.filter(request=self.item, actor=self.expert).exists())

    def test_expert_cannot_edit_another_domains_referral(self):
        referral = Referral.objects.create(request=self.item, domain=self.ai, expert=self.other_expert)
        self.client.force_login(self.expert)
        self.assertEqual(self.client.get(reverse("admin:services_referral_change", args=[referral.pk])).status_code, 302)

    def test_expert_cannot_edit_the_request_itself(self):
        Referral.objects.create(request=self.item, domain=self.fpga, expert=self.expert)
        self.client.force_login(self.expert)
        response = self.client.get(self.change_url())
        self.assertContains(response, "مشاهده درخواست خدمات")  # read-only view

    def test_quoted_total_and_money_summary(self):
        Referral.objects.create(request=self.item, domain=self.fpga, quoted_price=12_000_000)
        Referral.objects.create(request=self.item, domain=self.ai, quoted_price=8_000_000)
        self.assertEqual(self.item.quoted_total, 20_000_000)

        self.item.agreed_amount = 18_000_000
        self.item.save()
        RequestPayment.objects.create(request=self.item, amount=5_000_000, method="card")
        self.assertEqual(self.item.paid_total, 5_000_000)
        self.assertEqual(self.item.remaining, 13_000_000)
        self.assertEqual(self.item.payment_state, "پرداخت جزئی")

        RequestPayment.objects.create(request=self.item, amount=13_000_000, method="online")
        self.assertEqual(self.item.payment_state, "تسویه شده")

    def test_status_change_is_logged(self):
        self.client.force_login(self.admin)
        data = {
            "kind": "project", "status": "reviewing", "source": "site", "name": self.item.name,
            "mobile_number": self.item.mobile_number, "email": "", "contact_channel": "telegram",
            "contact_id": "@reza", "title": self.item.title, "domains": [self.fpga.pk],
            "other_domain": "", "level": "university", "need": "full", "description": DESCRIPTION,
            "deadline": "", "agreed_amount": "", "admin_note": "",
            "referrals-TOTAL_FORMS": "0", "referrals-INITIAL_FORMS": "0",
            "payments-TOTAL_FORMS": "0", "payments-INITIAL_FORMS": "0",
            "messages-TOTAL_FORMS": "0", "messages-INITIAL_FORMS": "0",
            "events-TOTAL_FORMS": "0", "events-INITIAL_FORMS": "0",
        }
        self.client.post(self.change_url(), data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "reviewing")
        self.assertTrue(RequestEvent.objects.filter(request=self.item, text__contains="در حال بررسی").exists())

    def test_expert_and_admin_talk_in_the_file(self):
        Referral.objects.create(request=self.item, domain=self.fpga, expert=self.expert)
        self.client.force_login(self.expert)
        self.client.post(reverse("admin:services_requestmessage_add"), {
            "request": self.item.pk, "body": "بودجه‌ی کاربر کم است، می‌شود ساده‌ترش کرد؟",
        })
        message = RequestMessage.objects.get()
        self.assertEqual(message.author, self.expert)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:services_requestmessage_changelist"))
        self.assertContains(response, "بودجه‌ی کاربر کم است")

    def test_manager_of_another_domain_cannot_read_the_messages(self):
        Referral.objects.create(request=self.item, domain=self.fpga, expert=self.expert)
        RequestMessage.objects.create(request=self.item, author=self.expert, body="یادداشت خصوصی")
        self.client.force_login(self.other_expert)
        response = self.client.get(reverse("admin:services_requestmessage_changelist"))
        self.assertNotContains(response, "یادداشت خصوصی")

    def test_admin_can_register_a_request_that_came_from_telegram(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:services_servicerequest_add"))
        self.assertEqual(response.status_code, 200)

        self.client.force_login(self.expert)
        self.assertEqual(self.client.get(reverse("admin:services_servicerequest_add")).status_code, 403)

    def test_attachment_is_protected(self):
        self.item.attachment.save("spec.pdf", SimpleUploadedFile("spec.pdf", b"%PDF-1.4"), save=True)
        url = reverse("services:attachment", args=["request", self.item.pk])
        stranger = User.objects.create_user("09128888888", PASSWORD)

        self.client.force_login(stranger)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.expert)
        self.assertEqual(self.client.get(url).status_code, 404)  # not referred yet

        Referral.objects.create(request=self.item, domain=self.fpga, expert=self.expert)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)


def tearDownModule():
    shutil.rmtree(TEMP_PROTECTED, ignore_errors=True)