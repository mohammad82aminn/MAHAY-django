"""
The office managers watch the staff and report to the site admins: they see the directory, the
activity and the figures, never the money, the inboxes or the customers, and change nothing.
"""
import shutil
import tempfile

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from accounts.roles import FINANCE_GROUP, OFFICE_GROUP, SITE_ADMINS_GROUP, TECH_ADMINS_GROUP
from approvals import services as approvals
from approvals.models import ChangeRequest
from domains.models import Domain
from inbox.models import Message
from products.models import Product

from .models import OfficeReport

PASSWORD = "S3cure-pass!"
TEMP_PROTECTED = tempfile.mkdtemp()


@override_settings(PROTECTED_MEDIA_ROOT=TEMP_PROTECTED)
class OfficeTestCase(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.office = self.person("09120000003", Group.objects.get(name=OFFICE_GROUP), "اداری")
        self.admin = self.person("09120000000", Group.objects.get(name=SITE_ADMINS_GROUP), "مدیرکل")
        self.manager = self.person("09121111111", self.fpga.managers_group, "مدیر")
        self.expert = self.person("09123333333", self.fpga.experts_group, "کارشناس")
        self.customer = User.objects.create_user("09350000000", PASSWORD, first_name="مشتری")

    @staticmethod
    def person(number, group, name):
        user = User.objects.create_user(number, PASSWORD, first_name=name)
        user.groups.add(group)
        user.refresh_from_db()
        return user

    def page(self, name, user=None, **params):
        self.client.force_login(user or self.office)
        return self.client.get(reverse(f"admin:office_{name}_changelist"), params)


class WhatTheOfficeSeesTests(OfficeTestCase):
    def test_the_staff_but_never_the_customers(self):
        listed = list(self.page("staffmember").context["cl"].queryset)
        self.assertIn(self.expert, listed)
        self.assertNotIn(self.customer, listed)

    def test_the_activity_without_the_money(self):
        product = Product.objects.create(product_type="course", title="دوره", slug="c", primary_domain=self.fpga)
        LogEntry.objects.create(user=self.manager, content_type=ContentType.objects.get_for_model(Product),
                                object_id=str(product.pk), object_repr="دوره", action_flag=CHANGE, change_message="[]")
        from finance.models import Payout

        LogEntry.objects.create(user=self.admin, content_type=ContentType.objects.get_for_model(Payout),
                                object_id="1", object_repr="تسویه‌ی محرمانه", action_flag=CHANGE, change_message="[]")
        response = self.page("activity")
        self.assertContains(response, "دوره")
        self.assertNotContains(response, "تسویه‌ی محرمانه")

    def test_nothing_of_finance_or_the_inboxes(self):
        self.client.force_login(self.office)
        # (their own کارپوشه they have, like everyone on the staff; nobody reads another's)
        for name in ("finance_receipt", "finance_financereport", "products_product"):
            with self.subTest(page=name):
                self.assertNotEqual(self.client.get(reverse(f"admin:{name}_changelist")).status_code, 200)

    def test_nobody_else_gets_in(self):
        for user in (self.manager, self.expert):
            with self.subTest(user=user.first_name):
                self.assertNotEqual(self.page("staffmember", user).status_code, 200)
        tech = self.person("09120000001", Group.objects.get(name=TECH_ADMINS_GROUP), "فنی")
        finance = self.person("09120000002", Group.objects.get(name=FINANCE_GROUP), "مالی")
        for user in (tech, finance):
            with self.subTest(user=user.first_name):
                self.assertNotEqual(self.page("performance", user).status_code, 200)

    def test_changes_nothing(self):
        self.client.force_login(self.office)
        url = reverse("admin:office_staffmember_change", args=[self.expert.pk])
        self.assertEqual(self.client.post(url, {"first_name": "دست‌کاری"}).status_code, 403)


class PerformanceTests(OfficeTestCase):
    def test_the_figures(self):
        product = Product.objects.create(product_type="course", title="دوره", slug="c", primary_domain=self.fpga,
                                         cover="products/covers/test.png")  # a cover is needed to publish
        request = approvals.submit(product, ChangeRequest.Action.CREATE, self.expert, self.fpga)
        approvals.forward(request, self.manager)
        approvals.approve(request, self.admin)
        rows = {row["person"]: row["values"] for row in self.page("performance", period="all").context["rows"]}
        from .performance import COLUMNS

        column = {key: index for index, (key, _label) in enumerate(COLUMNS)}
        self.assertEqual(rows[self.expert][column["submitted"]], 1)
        self.assertEqual(rows[self.expert][column["approved"]], 1)
        self.assertEqual(rows[self.manager][column["reviewed"]], 1)
        self.assertNotIn(self.customer, rows)

    def test_costs_the_same_for_more_people(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.page("performance")

        def count():
            with CaptureQueriesContext(connection) as captured:
                self.page("performance", period="all")
            return len(captured)

        before = count()
        for index in range(4):
            self.person(f"0912700000{index}", self.fpga.experts_group, f"کارشناس {index}")
        self.assertEqual(count(), before)

    def test_export(self):
        response = self.page("performance", export="1")
        self.assertIn("کارشناس", response.content.decode("utf-8-sig"))


class ReportTests(OfficeTestCase):
    def write(self):
        self.client.force_login(self.office)
        self.client.post(reverse("admin:office_officereport_add"), {
            "title": "گزارش ماهانه", "body": "همه‌چیز رو به راه است.", "period_from": "", "period_to": "",
            "files-TOTAL_FORMS": "0", "files-INITIAL_FORMS": "0",
        })
        return OfficeReport.objects.get()

    def test_the_site_admins_hear_read_and_answer(self):
        report = self.write()
        self.assertEqual(report.author, self.office)
        self.assertTrue(Message.objects.filter(deliveries__user=self.admin, subject__contains="گزارش ماهانه").exists())

        self.client.force_login(self.admin)
        url = reverse("admin:office_officereport_change", args=[report.pk])
        self.client.get(url)
        report.refresh_from_db()
        self.assertEqual(report.read_by, self.admin)
        self.client.post(url, {"reply": "ممنون.", "files-TOTAL_FORMS": "0", "files-INITIAL_FORMS": "0"})
        report.refresh_from_db()
        self.assertEqual(report.reply, "ممنون.")
        self.assertTrue(Message.objects.filter(deliveries__user=self.office, body__contains="ممنون.").exists())

    def test_only_the_site_admins_and_the_author_see_it(self):
        report = self.write()
        other = self.person("09120000004", Group.objects.get(name=OFFICE_GROUP), "اداری دیگر")
        for user, sees in ((self.office, True), (self.admin, True), (other, False)):
            with self.subTest(user=user.first_name):
                self.assertEqual(report in self.page("officereport", user).context["cl"].queryset, sees)
        self.assertNotEqual(self.page("officereport", self.manager).status_code, 200)


def tearDownModule():
    shutil.rmtree(TEMP_PROTECTED, ignore_errors=True)
