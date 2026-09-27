"""The 48-hour reminders: to whom, how often, and never twice for the same wait."""
from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from accounts.roles import SITE_ADMINS_GROUP, TECH_ADMINS_GROUP
from approvals import services as approvals
from approvals.models import ChangeRequest
from domains.models import Domain
from products.models import Product
from services.models import Referral, ServiceRequest

from . import reminders
from .models import Message

PASSWORD = "S3cure-pass!"
LATER = timedelta(hours=49)


class ReminderTestCase(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.admin = self.person("09120000000", Group.objects.get(name=SITE_ADMINS_GROUP))
        self.tech = self.person("09120000001", Group.objects.get(name=TECH_ADMINS_GROUP))
        self.manager = self.person("09121111111", self.fpga.managers_group)
        self.expert = self.person("09123333333", self.fpga.experts_group)

    @staticmethod
    def person(number, group):
        user = User.objects.create_user(number, PASSWORD)
        user.groups.add(group)
        return user

    def product(self, slug="p"):
        return Product.objects.create(product_type="course", title=f"دوره {slug}", slug=slug, primary_domain=self.fpga)

    def inbox_of(self, user):
        return Message.objects.filter(deliveries__user=user, from_system=True)

    def run_at(self, when):
        return reminders.send_due(now=timezone.now() + when)


class ContentReminderTests(ReminderTestCase):
    def test_after_48_hours_the_managers_and_the_site_admins_hear_of_it(self):
        approvals.submit(self.product(), ChangeRequest.Action.CREATE, self.expert, self.fpga)
        self.assertEqual(self.run_at(timedelta(hours=47)), 0)  # not yet
        self.run_at(LATER)
        for user in (self.manager, self.admin):
            [message] = self.inbox_of(user)
            self.assertIn("دوره p", message.body)
        for user in (self.expert, self.tech):
            self.assertFalse(self.inbox_of(user).exists())

    def test_the_same_wait_is_never_reminded_twice(self):
        approvals.submit(self.product(), ChangeRequest.Action.CREATE, self.expert, self.fpga)
        self.run_at(LATER)
        self.assertEqual(self.run_at(LATER + timedelta(hours=5)), 0)
        self.assertEqual(self.inbox_of(self.manager).count(), 1)

    def test_a_new_wait_at_the_next_desk_is_reminded_again(self):
        request = approvals.submit(self.product(), ChangeRequest.Action.CREATE, self.expert, self.fpga)
        self.run_at(LATER)
        approvals.forward(request, self.manager)
        self.assertEqual(self.run_at(LATER), 1)  # now only the site admins' desk
        self.assertEqual(self.inbox_of(self.admin).count(), 2)
        self.assertEqual(self.inbox_of(self.manager).count(), 1)

    def test_everything_overdue_comes_in_one_message(self):
        for slug in ("a", "b", "c"):
            approvals.submit(self.product(slug), ChangeRequest.Action.CREATE, self.expert, self.fpga)
        self.run_at(LATER)
        [message] = self.inbox_of(self.manager)
        self.assertIn("۳ کار", message.subject)
        for slug in ("a", "b", "c"):
            self.assertIn(f"دوره {slug}", message.body)


class OrderReminderTests(ReminderTestCase):
    def setUp(self):
        super().setUp()
        self.request = ServiceRequest.objects.create(
            kind="project", name="x", mobile_number="09350000000", contact_channel="phone",
            title="ربات", description="d" * 40, level="university", need="full",
        )

    def test_no_expert_picked_reminds_the_managers(self):
        Referral.objects.create(request=self.request, domain=self.fpga)
        self.run_at(LATER)
        self.assertIn("منتظر انتخاب کارشناس", self.inbox_of(self.manager).get().body)

    def test_a_price_nobody_agreed_to_reminds_the_managers(self):
        Referral.objects.create(request=self.request, domain=self.fpga, expert=self.expert,
                                quoted_price=5_000_000, quoted_at=timezone.now())
        self.run_at(LATER)
        self.assertIn("منتظر تأیید قیمت", self.inbox_of(self.manager).get().body)
        self.assertFalse(self.inbox_of(self.expert).exists())

    def test_work_not_started_reminds_the_expert(self):
        Referral.objects.create(request=self.request, domain=self.fpga, expert=self.expert, assigned_at=timezone.now())
        self.run_at(LATER)
        self.assertIn("هنوز شروع نشده", self.inbox_of(self.expert).get().body)
        self.assertFalse(self.inbox_of(self.manager).exists())

    def test_a_closed_request_is_left_alone(self):
        Referral.objects.create(request=self.request, domain=self.fpga)
        self.request.status = ServiceRequest.Status.CANCELED
        self.request.save(update_fields=["status"])
        self.assertEqual(self.run_at(LATER), 0)

    def test_the_command_runs(self):
        out = StringIO()
        call_command("send_reminders", stdout=out)
        self.assertIn("message(s) sent", out.getvalue())
