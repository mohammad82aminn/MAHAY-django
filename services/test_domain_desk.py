"""
Project orders and consultations through a domain's manager: the site admin names the domain,
its manager picks the expert and agrees to the expert's price, and only then does the price reach
the site admin. A domain with no manager keeps the old way, with the site admin doing both.
"""
from django.urls import reverse

from accounts.models import User
from inbox.models import Message

from . import services
from .models import Referral, RequestEvent, ServiceRequest
from .tests import PASSWORD, ServiceTestCase


class DomainDeskTestCase(ServiceTestCase):
    def setUp(self):
        super().setUp()  # self.expert manages FPGA, self.other_expert manages AI, self.admin is a site admin
        self.manager = self.expert
        self.worker = self.person("09123333333", "رضا", self.fpga.experts_group)
        self.colleague = self.person("09124444444", "مریم", self.fpga.experts_group)
        self.submit()
        self.item = ServiceRequest.objects.get()

    @staticmethod
    def person(number, name, group):
        user = User.objects.create_user(number, PASSWORD, first_name=name)
        user.groups.add(group)
        user.refresh_from_db()
        return user

    def refer(self, domain, expert=None):
        """The site admin's inline on the request page."""
        self.client.force_login(self.admin)
        return self.client.post(reverse("admin:services_servicerequest_change", args=[self.item.pk]), {
            "tracking_code": self.item.tracking_code, "kind": self.item.kind, "status": self.item.status,
            "source": self.item.source, "name": self.item.name, "mobile_number": self.item.mobile_number,
            "email": "", "contact_channel": self.item.contact_channel, "contact_id": self.item.contact_id,
            "heard_from": "instagram", "heard_from_other": "",
            "title": self.item.title, "domains": [domain.pk], "other_domain": "",
            "level": self.item.level, "need": self.item.need, "description": self.item.description,
            "deadline": "", "agreed_amount": "", "prepay_override": "", "admin_note": "",
            "referrals-TOTAL_FORMS": "1", "referrals-INITIAL_FORMS": "0",
            "referrals-0-request": self.item.pk, "referrals-0-domain": domain.pk,
            "referrals-0-expert": expert.pk if expert else "",
            "referrals-0-status": Referral.Status.REFERRED, "referrals-0-quoted_price": "",
            "referrals-0-duration_text": "",
            "payments-TOTAL_FORMS": "0", "payments-INITIAL_FORMS": "0",
            "messages-TOTAL_FORMS": "0", "messages-INITIAL_FORMS": "0",
            "events-TOTAL_FORMS": "0", "events-INITIAL_FORMS": "0",
        })

    def report(self, user, referral, **changes):
        """The referral page, as its manager or expert fills it in."""
        self.client.force_login(user)
        data = {
            "expert": referral.expert_id or "", "status": referral.status,
            "quoted_price": referral.quoted_price or "", "duration_text": "", "feasibility": "",
            "done_work": "", "remaining_work": "", "attachment": "",
        }
        data.update(changes)
        return self.client.post(reverse("admin:services_referral_change", args=[referral.pk]), data)

    def stage(self):
        return services.stage_of(ServiceRequest.objects.get(pk=self.item.pk))[0]

    def count_for(self, user):
        from django.contrib import admin

        fake = type("Request", (), {"user": user})()
        return admin.site._registry[Referral].pending_count(fake)


class ReferringTests(DomainDeskTestCase):
    def test_the_site_admin_names_the_domain_and_its_manager_picks_the_expert(self):
        response = self.refer(self.fpga, expert=self.worker)
        self.assertContains(response, "انتخاب کارشناس با مدیر حوزه است")
        self.assertFalse(Referral.objects.exists())

        self.refer(self.fpga)
        referral = Referral.objects.get()
        self.assertEqual(self.stage(), "assign")
        self.assertEqual(self.count_for(self.manager), 1)

        self.report(self.manager, referral, expert=self.worker.pk)
        referral.refresh_from_db()
        self.assertEqual(referral.expert, self.worker)
        self.assertEqual(self.stage(), "quotes")
        [message] = Message.objects.filter(deliveries__user=self.worker)
        self.assertTrue(message.from_system)
        self.assertIn(self.item.tracking_code, message.subject)
        self.assertTrue(RequestEvent.objects.filter(request=self.item, text__contains="سپرده شد").exists())

    def test_a_domain_with_no_manager_is_referred_the_old_way(self):
        self.manager.groups.remove(self.fpga.managers_group)
        self.refer(self.fpga, expert=self.worker)
        self.assertEqual(Referral.objects.get().expert, self.worker)
        self.assertTrue(Message.objects.filter(deliveries__user=self.worker).exists())

    def test_the_site_admin_is_counted_only_for_domains_with_no_manager(self):
        Referral.objects.create(request=self.item, domain=self.fpga)
        self.assertEqual(self.count_for(self.admin), 0)
        self.manager.groups.remove(self.fpga.managers_group)
        self.assertEqual(self.count_for(self.admin), 1)


class WhoSeesWhatTests(DomainDeskTestCase):
    def test_an_expert_sees_only_what_was_handed_to_them(self):
        referral = Referral.objects.create(request=self.item, domain=self.fpga, expert=self.worker)
        changelist = reverse("admin:services_servicerequest_changelist")
        referral_url = reverse("admin:services_referral_change", args=[referral.pk])

        for user, sees in ((self.worker, True), (self.manager, True), (self.colleague, False)):
            with self.subTest(user=user.first_name):
                self.client.force_login(user)
                listed = list(self.client.get(changelist).context["cl"].queryset)
                self.assertEqual(listed, [self.item] if sees else [])
                self.assertEqual(self.client.get(referral_url).status_code, 200 if sees else 302)

    def test_an_expert_cannot_hand_the_work_on(self):
        referral = Referral.objects.create(request=self.item, domain=self.fpga, expert=self.worker)
        self.report(self.worker, referral, expert=self.colleague.pk, duration_text="۲ هفته")
        referral.refresh_from_db()
        self.assertEqual(referral.expert, self.worker)
        self.assertEqual(referral.duration_text, "۲ هفته")  # the rest of the report is theirs


class PriceTests(DomainDeskTestCase):
    def setUp(self):
        super().setUp()
        self.referral = Referral.objects.create(request=self.item, domain=self.fpga, expert=self.worker)

    def test_an_expert_s_price_waits_for_a_manager(self):
        self.report(self.worker, self.referral, quoted_price=9_000_000)
        self.referral.refresh_from_db()
        self.assertIsNone(self.referral.quote_approved_at)
        self.assertEqual(self.stage(), "quote_review")
        self.assertEqual(self.count_for(self.manager), 1)

        self.client.force_login(self.manager)
        page = self.client.get(reverse("admin:services_referral_change", args=[self.referral.pk]))
        self.assertContains(page, "منتظر تأیید مدیر حوزه")
        self.report(self.manager, self.referral, quoted_price=9_000_000, approve_quote="on")
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.quote_approved_by, self.manager)
        self.assertEqual(self.stage(), "amount")
        self.assertEqual(self.count_for(self.manager), 0)

    def test_changing_the_price_after_it_was_agreed_asks_again(self):
        self.report(self.worker, self.referral, quoted_price=9_000_000)
        self.report(self.manager, self.referral, quoted_price=9_000_000, approve_quote="on")
        self.referral.refresh_from_db()
        self.report(self.worker, self.referral, quoted_price=11_000_000)
        self.referral.refresh_from_db()
        self.assertIsNone(self.referral.quote_approved_at)

    def test_a_manager_setting_the_price_has_agreed_to_it(self):
        self.report(self.manager, self.referral, quoted_price=7_000_000)
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.quote_approved_by, self.manager)

    def test_an_expert_cannot_approve_their_own_price(self):
        self.report(self.worker, self.referral, quoted_price=9_000_000)
        self.referral.refresh_from_db()
        self.report(self.worker, self.referral, quoted_price=9_000_000, approve_quote="on")
        self.referral.refresh_from_db()
        self.assertIsNone(self.referral.quote_approved_at)

    def test_in_a_domain_with_no_manager_the_expert_s_price_goes_straight_on(self):
        self.manager.groups.remove(self.fpga.managers_group)
        self.report(self.worker, self.referral, quoted_price=9_000_000)
        self.referral.refresh_from_db()
        self.assertIsNotNone(self.referral.quote_approved_at)
        self.assertEqual(self.stage(), "amount")


class ConsultationTests(DomainDeskTestCase):
    def test_a_consultation_needs_an_expert_but_no_price(self):
        self.fpga.consulting_rate = 400_000
        self.fpga.save()
        self.submit("services:consulting", minutes=30, title="مشاوره")
        consultation = ServiceRequest.objects.get(kind="consulting")
        self.assertIsNotNone(consultation.agreed_amount)  # priced on arrival from the domain's rate

        referral = Referral.objects.create(request=consultation, domain=self.fpga)
        self.report(self.manager, referral, expert=self.worker.pk)
        referral.refresh_from_db()
        self.assertEqual(referral.expert, self.worker)
        self.assertEqual(services.stage_of(consultation)[0], "prepay")
