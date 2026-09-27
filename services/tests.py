import shutil
import tempfile
from unittest.mock import patch

from commerce import gateway
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
        self.expert.groups.add(self.fpga.managers_group)
        self.other_expert = User.objects.create_user("09122222222", PASSWORD, first_name="سارا")
        self.other_expert.groups.add(self.ai.managers_group)

    def form_data(self, **changes):
        data = {
            "name": "رضا محمدی", "mobile_number": "09351234567", "email": "",
            "contact_channel": "telegram", "contact_id": "@reza", "heard_from": "instagram",
            "title": "ربات تعقیب خط", "domains": [self.fpga.pk], "other_domain": "",
            "level": "university", "need": "full", "description": DESCRIPTION, "deadline": "",
        }
        data.update(changes)
        return data

    def submit(self, url_name="services:project", **changes):
        return self.client.post(reverse(url_name), self.form_data(**changes), follow=True)

    def consulting_data(self, **changes):
        """What the consulting form asks for: a duration, and none of the project questions."""
        data = self.form_data(**{"domains": [self.ai.pk], "minutes": 30, **changes})
        for field in ("level", "need", "deadline"):
            data.pop(field, None)
        return data

    def consult(self, **changes):
        return self.client.post(reverse("services:consulting"), self.consulting_data(**changes),
                                follow=True)


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
        self.consult()
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

    def referral_payload(self, **changes):
        """The inline formset the admin posts when referring a request to a domain."""
        data = {
            "tracking_code": self.item.tracking_code, "kind": self.item.kind, "status": self.item.status,
            "source": self.item.source, "name": self.item.name, "mobile_number": self.item.mobile_number,
            "email": "", "contact_channel": self.item.contact_channel, "contact_id": self.item.contact_id,
            "title": self.item.title, "domains": [self.fpga.pk], "other_domain": "",
            "level": self.item.level, "need": self.item.need, "description": self.item.description,
            "deadline": "", "agreed_amount": "", "admin_note": "",
            "referrals-TOTAL_FORMS": "1", "referrals-INITIAL_FORMS": "0",
            "referrals-0-request": self.item.pk, "referrals-0-domain": self.fpga.pk,
            "referrals-0-status": Referral.Status.REFERRED, "referrals-0-quoted_price": "",
            "referrals-0-duration_text": "",
            "payments-TOTAL_FORMS": "0", "payments-INITIAL_FORMS": "0",
            "messages-TOTAL_FORMS": "0", "messages-INITIAL_FORMS": "0",
            "events-TOTAL_FORMS": "0", "events-INITIAL_FORMS": "0",
        }
        data.update(changes)
        return data

    def test_referring_moves_the_request_off_new(self):
        # Otherwise the panel keeps a red mark on a request the admin has already acted on
        self.assertEqual(self.item.status, ServiceRequest.Status.NEW)
        self.client.force_login(self.admin)
        self.client.post(self.change_url(), self.referral_payload())

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.REFERRED)
        self.assertEqual(Referral.objects.count(), 1)

    def test_referring_does_not_overwrite_a_status_someone_chose(self):
        self.item.status = ServiceRequest.Status.IN_PROGRESS
        self.item.save(update_fields=["status"])

        self.client.force_login(self.admin)
        self.client.post(self.change_url(), self.referral_payload(status=ServiceRequest.Status.IN_PROGRESS))

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.IN_PROGRESS)

    def test_the_status_change_is_written_into_the_history(self):
        self.client.force_login(self.admin)
        self.client.post(self.change_url(), self.referral_payload())
        self.assertTrue(
            RequestEvent.objects.filter(request=self.item, text__contains="ارجاع شده").exists()
        )

    def test_the_stage_follows_the_work_without_being_stored(self):
        stage = lambda: services.stage_of(ServiceRequest.objects.get(pk=self.item.pk))[0]
        self.assertEqual(stage(), "review")  # no referral yet

        referral = Referral.objects.create(request=self.item, domain=self.fpga, expert=self.expert)
        self.assertEqual(stage(), "quotes")  # waiting for a price

        referral.quoted_price = 5_000_000
        referral.save(update_fields=["quoted_price"])
        self.assertEqual(stage(), "amount")  # waiting for the admin to settle a total

        self.item.agreed_amount = 5_000_000
        self.item.save(update_fields=["agreed_amount"])
        self.assertEqual(stage(), "prepay")  # waiting for the customer

        RequestPayment.objects.create(request=self.item, amount=2_500_000, method="online")
        self.assertEqual(stage(), "working")  # the expert's turn

        referral.status = Referral.Status.DONE
        referral.save(update_fields=["status"])
        self.assertEqual(stage(), "settle")  # delivered, money outstanding

        RequestPayment.objects.create(request=self.item, amount=2_500_000, method="online")
        self.assertEqual(stage(), "done")

    def test_a_cancelled_request_is_simply_closed(self):
        self.item.status = ServiceRequest.Status.CANCELED
        self.item.save(update_fields=["status"])
        self.assertEqual(services.stage_of(self.item)[0], "closed")

    def test_the_expert_page_leaves_out_what_is_none_of_their_business(self):
        Referral.objects.create(request=self.item, domain=self.fpga, expert=self.expert)
        self.client.force_login(self.expert)
        response = self.client.get(self.change_url())

        self.assertNotContains(response, "admin_note")
        self.assertNotContains(response, "payments-TOTAL_FORMS")
        self.assertNotContains(response, "events-TOTAL_FORMS")

    def test_the_admin_still_sees_the_whole_file(self):
        Referral.objects.create(request=self.item, domain=self.fpga, expert=self.expert)
        self.client.force_login(self.admin)
        response = self.client.get(self.change_url())

        self.assertContains(response, "admin_note")
        self.assertContains(response, "payments-TOTAL_FORMS")
        self.assertContains(response, "events-TOTAL_FORMS")

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

class PaymentTests(ServiceTestCase):
    """
    Money is the part that has to be right. Every test here asks the same question from a
    different angle: can anything other than a confirmed gateway response move the paid total?
    """

    def setUp(self):
        super().setUp()
        self.buyer = User.objects.create_user("09361234567", PASSWORD, first_name="خریدار")
        self.item = ServiceRequest.objects.create(
            kind=ServiceRequest.Kind.PROJECT, user=self.buyer, name="خریدار",
            mobile_number="+989361234567", contact_channel="telegram", contact_id="@b",
            title="ربات", description=DESCRIPTION, level="university", need="full",
            agreed_amount=10_000_000,
        )
        self.pay_url = reverse("services:pay", args=[self.item.tracking_code])
        self.callback_url = reverse("services:payment_callback")

    def start_payment(self):
        self.client.force_login(self.buyer)
        with patch("commerce.gateway.start", return_value=("AUTH123", "https://gateway/pay")) as started:
            response = self.client.post(self.pay_url)
        return response, started

    def confirm(self, authority="AUTH123", status="OK", data=None):
        with patch("commerce.gateway.confirm", return_value=data or {"ref_id": "55", "card_pan": "6037"}):
            return self.client.get(self.callback_url, {"Authority": authority, "Status": status})

    # --- what is owed -------------------------------------------------------------

    def test_the_prepayment_is_half_and_the_browser_never_says_so(self):
        self.assertEqual(self.item.due_now, 5_000_000)
        _response, started = self.start_payment()
        self.assertEqual(started.call_args.kwargs["amount"], 5_000_000)

    def test_a_consultation_is_asked_for_in_full(self):
        self.item.kind = ServiceRequest.Kind.CONSULTING
        self.item.save(update_fields=["kind"])
        self.assertEqual(self.item.prepay_percent, 100)
        self.assertEqual(self.item.due_now, 10_000_000)

    def test_the_rest_is_owed_after_the_prepayment(self):
        self.start_payment()
        self.confirm()
        self.item.refresh_from_db()
        self.assertEqual(self.item.paid_total, 5_000_000)
        self.assertEqual(self.item.due_now, 5_000_000)

    # --- who may pay --------------------------------------------------------------

    def test_a_stranger_cannot_pay_for_somebody_elses_request(self):
        self.client.force_login(self.expert)
        self.assertEqual(self.client.post(self.pay_url).status_code, 404)

    def test_a_request_with_no_account_behind_it_cannot_be_paid(self):
        self.item.user = None
        self.item.save(update_fields=["user"])
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.post(self.pay_url).status_code, 404)

    # --- only the gateway moves money ---------------------------------------------

    def test_arriving_at_the_callback_is_not_payment(self):
        self.start_payment()
        response = self.client.get(self.callback_url, {"Authority": "AUTH123", "Status": "NOK"})

        self.item.refresh_from_db()
        self.assertEqual(self.item.paid_total, 0)
        self.assertEqual(RequestPayment.objects.get().status, RequestPayment.Status.FAILED)
        self.assertEqual(response.status_code, 302)

    def test_a_refused_verification_counts_nothing(self):
        self.start_payment()
        with patch("commerce.gateway.confirm", side_effect=gateway.PaymentError("رد شد")):
            self.client.get(self.callback_url, {"Authority": "AUTH123", "Status": "OK"})

        self.item.refresh_from_db()
        self.assertEqual(self.item.paid_total, 0)
        self.assertEqual(RequestPayment.objects.get().status, RequestPayment.Status.FAILED)

    def test_an_unknown_authority_is_ignored(self):
        self.start_payment()
        self.confirm(authority="SOMETHING-ELSE")
        self.item.refresh_from_db()
        self.assertEqual(self.item.paid_total, 0)

    def test_refreshing_the_callback_does_not_pay_twice(self):
        self.start_payment()
        self.confirm()
        self.confirm()

        self.item.refresh_from_db()
        self.assertEqual(self.item.paid_total, 5_000_000)
        self.assertEqual(RequestPayment.objects.filter(status=RequestPayment.Status.PAID).count(), 1)

    def test_walking_away_and_starting_again_leaves_one_open_attempt(self):
        self.start_payment()
        self.start_payment()
        self.assertEqual(RequestPayment.objects.filter(status=RequestPayment.Status.PENDING).count(), 1)
        self.assertEqual(RequestPayment.objects.filter(status=RequestPayment.Status.FAILED).count(), 1)

    def test_a_pending_payment_is_not_counted_as_money(self):
        self.start_payment()
        self.item.refresh_from_db()
        self.assertEqual(self.item.paid_total, 0)
        self.assertEqual(services.stage_of(self.item)[0], "prepay")


class GuestClaimTests(ServiceTestCase):
    def test_signing_up_picks_up_the_requests_sent_from_that_number(self):
        # The form takes guests, but paying needs an account, so the two have to meet somewhere
        self.submit()
        item = ServiceRequest.objects.get()
        self.assertIsNone(item.user)

        owner = User.objects.create_user("09351234567", PASSWORD, first_name="رضا")
        services.claim_guest_requests(owner)

        item.refresh_from_db()
        self.assertEqual(item.user, owner)

    def test_somebody_elses_request_is_not_picked_up(self):
        self.submit()
        stranger = User.objects.create_user("09129998877", PASSWORD, first_name="غریبه")
        services.claim_guest_requests(stranger)

        self.assertIsNone(ServiceRequest.objects.get().user)


class ConsultingTests(ServiceTestCase):
    """
    A consultation is a conversation, not a delivery: one expert, a published rate, paid before
    it happens. The project questions would only be noise in front of somebody booking one.
    """

    def setUp(self):
        super().setUp()
        self.ai.consulting_rate = 200_000
        self.ai.save(update_fields=["consulting_rate"])

    def test_the_form_does_not_ask_a_project_question(self):
        response = self.client.get(reverse("services:consulting"))
        for field in ("level", "need", "deadline"):
            with self.subTest(field=field):
                self.assertNotContains(response, f'name="{field}"')
        self.assertContains(response, 'name="minutes"')

    def test_the_project_form_is_untouched(self):
        response = self.client.get(reverse("services:project"))
        for field in ("level", "need", "deadline"):
            with self.subTest(field=field):
                self.assertContains(response, f'name="{field}"')
        self.assertNotContains(response, 'name="minutes"')

    def test_the_price_is_on_the_request_the_moment_it_arrives(self):
        self.consult()
        item = ServiceRequest.objects.get()
        self.assertEqual(item.minutes, 30)
        self.assertEqual(item.agreed_amount, 400_000)  # two quarters at the domain's rate
        self.assertEqual(services.stage_of(item)[0], "prepay")

    def test_a_part_quarter_is_charged_as_a_whole_one(self):
        self.consult(minutes=45)
        self.assertEqual(ServiceRequest.objects.get().agreed_amount, 600_000)

    def test_a_consultation_is_paid_in_full(self):
        self.consult()
        item = ServiceRequest.objects.get()
        self.assertEqual(item.prepay_percent, 100)
        self.assertEqual(item.due_now, item.agreed_amount)

    def test_only_one_domain_may_be_chosen(self):
        response = self.consult(domains=[self.ai.pk, self.fpga.pk])
        self.assertContains(response, "فقط یک حوزه")
        self.assertFalse(ServiceRequest.objects.exists())

    def test_a_domain_without_a_rate_leaves_the_price_open(self):
        self.consult(domains=[self.fpga.pk])  # fpga has no rate and there is no site default
        item = ServiceRequest.objects.get()
        self.assertIsNone(item.consulting_price)
        self.assertIsNone(item.agreed_amount)
        self.assertEqual(services.stage_of(item)[0], "review")

    def test_a_project_never_gets_a_consulting_price(self):
        self.submit()
        item = ServiceRequest.objects.get()
        self.assertIsNone(item.consulting_price)
        self.assertIsNone(item.agreed_amount)


class HeardFromTests(ServiceTestCase):
    """«از کجا با ما آشنا شدید؟»: asked of everyone, read only by the site admins."""

    def test_the_question_is_required_on_both_forms(self):
        for url_name in ("services:project", "services:consulting"):
            with self.subTest(form=url_name):
                response = self.submit(url_name, heard_from="", minutes=30)
                self.assertContains(response, "یکی از گزینه‌ها را انتخاب کنید.")
        self.assertFalse(ServiceRequest.objects.exists())

    def test_the_answer_is_kept(self):
        self.submit(heard_from="aparat")
        self.assertEqual(ServiceRequest.objects.get().heard_from, "aparat")

    def test_other_needs_words_and_only_other_keeps_them(self):
        response = self.submit(heard_from="other", heard_from_other=" ")
        self.assertContains(response, "بنویسید از کجا با ما آشنا شدید.")
        self.submit(heard_from="other", heard_from_other="نمایشگاه الکامپ")
        self.submit(heard_from="telegram", heard_from_other="جا مانده از انتخاب قبلی", title="دومی")
        self.assertEqual(ServiceRequest.objects.get(title="ربات تعقیب خط").heard_from_other, "نمایشگاه الکامپ")
        self.assertEqual(ServiceRequest.objects.get(title="دومی").heard_from_other, "")

    def test_the_expert_never_sees_the_answer(self):
        self.submit(heard_from="other", heard_from_other="نمایشگاه الکامپ")
        item = ServiceRequest.objects.get()
        Referral.objects.create(request=item, domain=self.fpga, expert=self.expert)
        url = reverse("admin:services_servicerequest_change", args=[item.pk])
        self.client.force_login(self.expert)
        self.assertNotContains(self.client.get(url), "نمایشگاه الکامپ")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), "نمایشگاه الکامپ")


class HeardFromReportTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("admin:services_heardfromreport_changelist")
        self.submit(heard_from="instagram")
        self.submit(heard_from="instagram", title="دومی")
        self.submit("services:consulting", heard_from="other", heard_from_other="نمایشگاه الکامپ", minutes=30)
        ServiceRequest.objects.create(kind="project", name="x", mobile_number="09350000000",
                                      contact_channel="phone", title="ثبت دستی", description=DESCRIPTION,
                                      level="university", need="full")  # typed in by an admin: no answer

    def test_site_and_tech_admins_read_the_counts(self):
        for user in (self.admin, self.tech):
            with self.subTest(user=user.first_name):
                self.client.force_login(user)
                response = self.client.get(self.url, {"period": "all"})
                rows = {row["label"]: row for row in response.context["rows"]}
                self.assertEqual(rows["اینستاگرام"]["cells"], [2, 0, 0])
                self.assertEqual(rows["سایر"]["cells"], [0, 1, 0])
                self.assertEqual(rows["بدون پاسخ"]["total"], 1)
                self.assertEqual(response.context["answered"], 3)
                self.assertEqual(rows["اینستاگرام"]["percent"], 67)
                self.assertContains(response, "نمایشگاه الکامپ")

    def test_nobody_else_gets_the_page_or_the_menu_entry(self):
        self.client.force_login(self.expert)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertNotContains(self.client.get(reverse("admin:index")), self.url)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("admin:index")), self.url)

    def test_the_report_takes_a_fixed_number_of_queries(self):
        self.client.force_login(self.admin)
        self.client.get(self.url)  # warm the session and the admin's own lookups
        before = self.queries_for_one_view()
        for index in range(5):
            self.submit(heard_from="other", heard_from_other=f"جای {index}", title=f"بیشتر {index}")
        self.assertEqual(self.queries_for_one_view(), before)

    def queries_for_one_view(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as captured:
            self.client.get(self.url, {"period": "all"})
        return len(captured)
