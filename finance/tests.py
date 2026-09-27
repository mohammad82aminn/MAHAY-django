"""
The ledger: a receipt for every toman that arrives, divided exactly by the percentages in force
at the time, never double-counted, voided (not lost) when a payment is undone, and seen only by the
finance managers and the site admins.
"""
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from accounts.roles import FINANCE_GROUP, SITE_ADMINS_GROUP
from commerce.models import Order, OrderItem
from domains.models import Domain
from inbox.models import Message
from products.models import Product
from services.models import Referral, RequestPayment, ServiceRequest

from . import shares
from .models import DomainShareRule, ProductShareRule, Receipt, RequestShareRule, Share

PASSWORD = "S3cure-pass!"


class FinanceTestCase(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.ai = Domain.objects.create(name="هوش مصنوعی", slug="ai")
        self.admin = self.person("09120000000", Group.objects.get(name=SITE_ADMINS_GROUP))
        self.finance = self.person("09120000002", Group.objects.get(name=FINANCE_GROUP))
        self.manager = self.person("09121111111", self.fpga.managers_group)
        self.expert = self.person("09123333333", self.fpga.experts_group)
        self.teacher = self.person("09124444444", self.fpga.experts_group)
        self.buyer = User.objects.create_user("09350000000", PASSWORD, first_name="خریدار")
        self.course = Product.objects.create(
            product_type="course", title="دوره FPGA", slug="fpga", primary_domain=self.fpga, price=1_000_000,
        )
        self.course.instructors.add(self.teacher)

    @staticmethod
    def person(number, group):
        user = User.objects.create_user(number, PASSWORD, first_name=f"نفر {number[-2:]}")
        user.groups.add(group)
        user.refresh_from_db()
        return user

    def set_sale(self, domain, instructor, manager, fund):
        DomainShareRule.objects.filter(domain=domain).update(
            sale_instructor=instructor, sale_manager=manager, sale_fund=fund,
        )

    def set_service(self, domain, expert, manager, fund):
        DomainShareRule.objects.filter(domain=domain).update(
            service_expert=expert, service_manager=manager, service_fund=fund,
        )

    def buy(self, *priced_products):
        order = Order.objects.create(user=self.buyer, total=sum(price for _p, price in priced_products))
        for product, price in priced_products:
            OrderItem.objects.create(order=order, product=product, title=product.title, price=price)
        with self.captureOnCommitCallbacks(execute=True):
            order.mark_paid(reference_id="REF-1", card_pan="6037****1234")
        return order

    def service_request(self, *referrals):
        request = ServiceRequest.objects.create(
            kind="project", name="مشتری", mobile_number="09351111111", contact_channel="phone",
            title="ربات", description="d" * 40, level="university", need="full",
        )
        for domain, expert, price in referrals:
            Referral.objects.create(request=request, domain=domain, expert=expert, quoted_price=price,
                                    quote_approved_at="2026-01-01T00:00:00Z" if price else None)
        return request

    def pay(self, request, amount, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            return RequestPayment.objects.create(request=request, amount=amount, method="card", **extra)

    @staticmethod
    def split_of(receipt):
        return {(share.role, share.person_id, share.domain_id): share.amount for share in receipt.shares.all()}


class ReceiptTests(FinanceTestCase):
    def test_a_paid_order_makes_one_receipt_per_product_that_cost_something(self):
        free = Product.objects.create(product_type="course", title="رایگان", slug="free", primary_domain=self.fpga)
        self.buy((self.course, 800_000), (free, 0))
        receipt = Receipt.objects.get()
        self.assertEqual((receipt.amount, receipt.product, receipt.payer, receipt.source),
                         (800_000, self.course, self.buyer, Receipt.Source.SALE))
        self.assertEqual(receipt.card_pan, "6037****1234")

    def test_the_finance_managers_hear_of_it_at_once(self):
        self.buy((self.course, 800_000))
        [message] = Message.objects.filter(deliveries__user=self.finance)
        self.assertTrue(message.from_system)
        self.assertIn("دوره FPGA", message.body)
        self.assertIn("خریدار", message.body)
        self.assertFalse(Message.objects.filter(deliveries__user=self.manager).exists())

    def test_saving_the_order_again_never_counts_it_twice(self):
        order = self.buy((self.course, 800_000))
        order.save()
        self.assertEqual(Receipt.objects.count(), 1)

    def test_a_payment_entered_by_hand_counts_as_well(self):
        request = self.service_request((self.fpga, self.expert, 5_000_000))
        self.pay(request, 2_500_000, note="پیش‌پرداخت")
        receipt = Receipt.objects.get()
        self.assertEqual((receipt.amount, receipt.source, receipt.method), (2_500_000, "service", "card"))
        self.assertIn("پیش‌پرداخت", receipt.title)

    def test_an_undone_payment_voids_its_receipt_and_its_shares(self):
        self.set_service(self.fpga, 60, 10, 10)
        request = self.service_request((self.fpga, self.expert, 5_000_000))
        payment = self.pay(request, 1_000_000)
        payment.status = RequestPayment.Status.FAILED
        payment.save()
        receipt = Receipt.objects.get()
        self.assertTrue(receipt.is_void)
        self.assertFalse(receipt.shares.exists())

        other = self.pay(request, 500_000)
        other.delete()
        self.assertTrue(Receipt.objects.get(amount=500_000).is_void)

    def test_a_corrected_amount_is_divided_again(self):
        self.set_service(self.fpga, 60, 10, 10)
        payment = self.pay(self.service_request((self.fpga, self.expert, 5_000_000)), 1_000_000)
        payment.amount = 2_000_000
        payment.save()
        receipt = Receipt.objects.get()
        self.assertEqual(sum(receipt.shares.values_list("amount", flat=True)), 2_000_000)

    def test_an_order_taken_back_voids_its_receipts(self):
        order = self.buy((self.course, 800_000))
        order.status = Order.Status.CANCELED
        order.save()
        self.assertTrue(Receipt.objects.get().is_void)


class SaleSplitTests(FinanceTestCase):
    def test_divided_by_the_domain_s_percentages_to_the_toman(self):
        self.set_sale(self.fpga, 40, 10, 10)
        self.buy((self.course, 999_999))
        receipt = Receipt.objects.get()
        self.assertEqual(self.split_of(receipt), {
            ("instructor", self.teacher.pk, self.fpga.pk): 399_999,
            ("manager", self.manager.pk, self.fpga.pk): 99_999,
            ("fund", None, self.fpga.pk): 99_999,
            ("company", None, self.fpga.pk): 400_002,  # 40% plus what rounding left over
        })
        self.assertEqual(sum(self.split_of(receipt).values()), 999_999)

    def test_several_instructors_and_managers_share_equally(self):
        second_teacher = self.person("09125555555", self.fpga.experts_group)
        second_manager = self.person("09126666666", self.fpga.managers_group)
        self.course.instructors.add(second_teacher)
        self.set_sale(self.fpga, 50, 10, 0)
        self.buy((self.course, 1_000_000))
        shares_ = self.split_of(Receipt.objects.get())
        self.assertEqual(shares_[("instructor", self.teacher.pk, self.fpga.pk)], 250_000)
        self.assertEqual(shares_[("instructor", second_teacher.pk, self.fpga.pk)], 250_000)
        self.assertEqual(shares_[("manager", second_manager.pk, self.fpga.pk)], 50_000)
        self.assertNotIn(("fund", None, self.fpga.pk), shares_)  # 0% makes no share at all

    def test_without_percentages_it_waits_and_says_why(self):
        self.buy((self.course, 800_000))
        receipt = Receipt.objects.get()
        self.assertIsNone(receipt.split_at)
        self.assertIn("تعیین نشده", receipt.unsplit_reason)
        self.set_sale(self.fpga, 40, 10, 10)
        self.assertTrue(shares.split(receipt))
        self.assertEqual(sum(receipt.shares.values_list("amount", flat=True)), 800_000)

    def test_a_percentage_for_nobody_waits_rather_than_guessing(self):
        self.course.instructors.clear()
        self.set_sale(self.fpga, 40, 10, 10)
        self.buy((self.course, 800_000))
        self.assertIn("مدرسی", Receipt.objects.get().unsplit_reason)

    def test_a_product_s_own_percentages_come_first(self):
        self.set_sale(self.fpga, 40, 10, 10)
        ProductShareRule.objects.create(product=self.course, instructor=70, manager=0, fund=0)
        self.buy((self.course, 1_000_000))
        shares_ = self.split_of(Receipt.objects.get())
        self.assertEqual(shares_[("instructor", self.teacher.pk, self.fpga.pk)], 700_000)
        self.assertEqual(shares_[("company", None, self.fpga.pk)], 300_000)

    def test_changing_the_percentages_leaves_the_past_alone(self):
        self.set_sale(self.fpga, 40, 10, 10)
        self.buy((self.course, 1_000_000))
        self.set_sale(self.fpga, 10, 10, 10)
        shares_ = self.split_of(Receipt.objects.get())
        self.assertEqual(shares_[("instructor", self.teacher.pk, self.fpga.pk)], 400_000)

    def test_percentages_cannot_add_up_to_more_than_everything(self):
        rule = DomainShareRule.objects.get(domain=self.fpga)
        rule.sale_instructor, rule.sale_manager, rule.sale_fund = Decimal(80), Decimal(20), Decimal(1)
        with self.assertRaises(ValidationError):
            rule.full_clean()


class ServiceSplitTests(FinanceTestCase):
    def setUp(self):
        super().setUp()
        self.ai_expert = self.person("09127777777", self.ai.experts_group)
        self.ai_manager = self.person("09128888888", self.ai.managers_group)
        self.set_service(self.fpga, 60, 10, 10)
        self.set_service(self.ai, 50, 10, 0)

    def test_one_payment_is_spread_over_the_domains_by_their_agreed_prices(self):
        request = self.service_request((self.fpga, self.expert, 6_000_000), (self.ai, self.ai_expert, 4_000_000))
        self.pay(request, 5_000_000)
        shares_ = self.split_of(Receipt.objects.get())
        self.assertEqual(shares_[("expert", self.expert.pk, self.fpga.pk)], 1_800_000)   # 60% of 3,000,000
        self.assertEqual(shares_[("expert", self.ai_expert.pk, self.ai.pk)], 1_000_000)  # 50% of 2,000,000
        self.assertEqual(sum(shares_.values()), 5_000_000)

    def test_spread_evenly_while_a_price_is_still_missing(self):
        request = self.service_request((self.fpga, self.expert, 6_000_000), (self.ai, self.ai_expert, None))
        self.pay(request, 1_000_000)
        shares_ = self.split_of(Receipt.objects.get())
        self.assertEqual(shares_[("expert", self.expert.pk, self.fpga.pk)], 300_000)  # 60% of 500,000

    def test_no_expert_chosen_yet_waits(self):
        request = self.service_request((self.fpga, None, 6_000_000))
        self.pay(request, 1_000_000)
        receipt = Receipt.objects.get()
        self.assertIn("کارشناسی", receipt.unsplit_reason)
        Referral.objects.filter(request=request).update(expert=self.expert)
        self.assertTrue(shares.split(receipt))

    def test_an_order_s_own_percentages_come_first(self):
        request = self.service_request((self.fpga, self.expert, 6_000_000))
        RequestShareRule.objects.create(request=request, expert=80, manager=0, fund=0)
        self.pay(request, 1_000_000)
        self.assertEqual(self.split_of(Receipt.objects.get())[("expert", self.expert.pk, self.fpga.pk)], 800_000)


class WhoSeesTheMoneyTests(FinanceTestCase):
    def test_only_finance_managers_and_site_admins(self):
        self.buy((self.course, 800_000))
        url = reverse("admin:finance_receipt_changelist")
        for user, allowed in ((self.finance, True), (self.admin, True), (self.manager, False), (self.expert, False)):
            with self.subTest(user=user.mobile_number):
                self.client.force_login(user)
                self.assertEqual(self.client.get(url).status_code == 200, allowed)

    def test_the_finance_manager_sees_nothing_else_of_the_site(self):
        self.client.force_login(self.finance)
        for name in ("products_product", "services_servicerequest", "accounts_user", "content_lesson"):
            with self.subTest(page=name):
                self.assertNotEqual(self.client.get(reverse(f"admin:{name}_changelist")).status_code, 200)

    def test_the_red_number_counts_what_nobody_has_looked_at(self):
        from django.contrib import admin

        self.buy((self.course, 800_000))
        model_admin = admin.site._registry[Receipt]
        fake = type("Request", (), {"user": self.finance})()
        self.assertEqual(model_admin.pending_count(fake), 1)
        self.client.force_login(self.finance)
        self.client.post(reverse("admin:finance_receipt_changelist"), {
            "action": "mark_reviewed", "_selected_action": [Receipt.objects.get().pk],
        })
        self.assertEqual(model_admin.pending_count(fake), 0)

    def test_only_the_owner_makes_someone_a_finance_manager(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:accounts_user_change", args=[self.expert.pk]))
        offered = response.context["adminform"].form.fields["groups"].queryset
        self.assertNotIn(Group.objects.get(name=FINANCE_GROUP), offered)


class StartingTheLedgerTests(FinanceTestCase):
    def test_earlier_payments_get_a_quiet_receipt(self):
        from importlib import import_module

        from django.apps import apps

        request = self.service_request((self.fpga, self.expert, 6_000_000))
        self.pay(request, 1_000_000)
        Receipt.objects.all().delete()
        Message.objects.all().delete()

        import_module("finance.migrations.0002_existing_domains_and_payments").fill(apps, None)
        receipt = Receipt.objects.get()
        self.assertIsNotNone(receipt.reviewed_at)
        self.assertIsNone(receipt.split_at)
        self.assertFalse(Message.objects.exists())
        self.assertTrue(DomainShareRule.objects.filter(domain=self.ai).exists())


class BalanceTests(FinanceTestCase):
    def setUp(self):
        super().setUp()
        self.set_sale(self.fpga, 40, 10, 10)
        self.buy((self.course, 1_000_000))  # teacher 400,000 · manager 100,000 · fund 100,000

    def pay_out(self, **target):
        from datetime import date

        from .models import Payout

        return Payout.objects.create(amount=150_000, paid_on=date(2026, 9, 1), reference="BANK-1", **target)

    def test_what_is_owed_is_shares_less_payouts(self):
        from . import balances

        self.pay_out(person=self.teacher)
        self.pay_out(fund=self.fpga)
        rows = {row["person"]: row for row in balances.people()}
        self.assertEqual((rows[self.teacher]["earned"], rows[self.teacher]["paid"], rows[self.teacher]["owed"]),
                         (400_000, 150_000, 250_000))
        self.assertEqual(rows[self.manager]["owed"], 100_000)
        [fund] = balances.funds()
        self.assertEqual(fund["domain"], self.fpga)
        self.assertEqual((fund["earned"], fund["paid"], fund["owed"]), (100_000, 150_000, -50_000))  # overdrawn shows as such

    def test_a_voided_receipt_no_longer_counts(self):
        from . import balances, receipts

        receipts.void(Receipt.objects.get(), "test")
        self.assertEqual(balances.people(), [])

    def test_a_payout_goes_to_a_person_or_a_fund_never_both(self):
        from datetime import date

        from .models import Payout

        with self.assertRaises(ValidationError):
            Payout(person=self.teacher, fund=self.fpga, amount=1, paid_on=date(2026, 9, 1), reference="x").full_clean()
        with self.assertRaises(ValidationError):
            Payout(amount=1, paid_on=date(2026, 9, 1), reference="x").full_clean()

    def test_the_report_page_and_its_exports(self):
        self.client.force_login(self.finance)
        url = reverse("admin:finance_financereport_changelist")
        page = self.client.get(url, {"period": "all"})
        self.assertContains(page, "۱٬۰۰۰٬۰۰۰ تومان")
        self.assertContains(page, self.teacher.first_name)
        export = self.client.get(url, {"export": "people"})
        self.assertEqual(export["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("400000", export.content.decode("utf-8-sig"))

        self.client.force_login(self.manager)
        self.assertNotEqual(self.client.get(url).status_code, 200)

    def test_the_report_costs_the_same_however_many_receipts(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.force_login(self.finance)
        url = reverse("admin:finance_financereport_changelist")
        self.client.get(url)

        def count():
            with CaptureQueriesContext(connection) as captured:
                self.client.get(url, {"period": "all"})
            return len(captured)

        before = count()
        for index in range(4):
            other = Product.objects.create(product_type="course", title=f"دوره {index}", slug=f"c{index}",
                                           primary_domain=self.fpga, price=500_000)
            other.instructors.add(self.person(f"0912900000{index}", self.fpga.experts_group))
            self.buy((other, 500_000))
        self.assertEqual(count(), before)


class MyStatementTests(FinanceTestCase):
    def setUp(self):
        super().setUp()
        self.set_sale(self.fpga, 40, 10, 10)
        self.buy((self.course, 1_000_000))

    def statement(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("admin:finance_mystatement_changelist"))

    def test_everyone_sees_their_own_figures_only(self):
        page = self.statement(self.teacher)
        self.assertEqual(page.context["totals"]["earned"], 400_000)
        self.assertEqual([share.person for share in page.context["shares"]], [self.teacher])
        self.assertNotContains(page, "صندوق حوزه‌های من")

    def test_a_domain_manager_also_sees_their_domain_s_fund(self):
        page = self.statement(self.manager)
        self.assertEqual(page.context["totals"]["earned"], 100_000)
        self.assertEqual([row["domain"] for row in page.context["funds"]], [self.fpga])

    def test_a_customer_has_no_statement(self):
        self.assertNotEqual(self.statement(self.buyer).status_code, 200)


class MoneyFilterTests(TestCase):
    def test_zero_is_an_amount_not_free(self):
        from products.templatetags.store import money, toman

        self.assertEqual(money(0), "۰ تومان")
        self.assertEqual(money(None), "۰ تومان")
        self.assertEqual(money(1_500_000), "۱٬۵۰۰٬۰۰۰ تومان")
        self.assertEqual(toman(0), "رایگان")  # a price of zero still means free
