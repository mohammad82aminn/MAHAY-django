"""
The technical admins: they see the whole panel to find what is wrong, change nothing but the site's
own pages and contact channels, and never see the money, the CVs or anyone's inbox.
"""
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from domains.models import Domain
from products.models import Product

from .models import User
from .roles import OFFICE_GROUP, SITE_ADMINS_GROUP, TECH_ADMINS_GROUP, is_site_admin, sees_everything

PASSWORD = "S3cure-pass!"


class TechAdminTests(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.ai = Domain.objects.create(name="هوش مصنوعی", slug="ai")
        self.tech = User.objects.create_user("09120000001", PASSWORD, first_name="فنی")
        self.tech.groups.add(Group.objects.get(name=TECH_ADMINS_GROUP))
        self.product = Product.objects.create(product_type="course", title="دوره AI", slug="ai", primary_domain=self.ai)
        self.client.force_login(self.tech)

    def test_sees_everything_decides_nothing(self):
        self.assertTrue(sees_everything(self.tech))
        self.assertFalse(is_site_admin(self.tech))

    def test_every_domain_s_content_is_on_show_but_read_only(self):
        listed = self.client.get(reverse("admin:products_product_changelist")).context["cl"].queryset
        self.assertIn(self.product, listed)
        url = reverse("admin:products_product_change", args=[self.product.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {"title": "دست‌کاری"})
        self.assertEqual(response.status_code, 403)

    def test_the_money_the_cvs_and_the_office_are_closed(self):
        for name in ("finance_receipt", "finance_payout", "services_requestpayment", "commerce_order",
                     "collaboration_collaborationrequest", "services_heardfromreport"):
            with self.subTest(page=name):
                self.assertNotEqual(self.client.get(reverse(f"admin:{name}_changelist")).status_code, 200)

    def test_the_site_s_own_pages_are_theirs_to_edit(self):
        self.assertTrue(self.tech.has_perm("pages.change_page"))
        self.assertTrue(self.tech.has_perm("services.change_contactchannel"))
        self.assertFalse(self.tech.has_perm("pages.change_contactmessage"))  # visitors' messages: read only
        self.assertFalse(self.tech.has_perm("products.change_product"))

    def test_can_open_a_course_s_content_to_check_it(self):
        from content.access import can_open

        self.assertTrue(can_open(self.tech, self.product))

    def test_no_red_numbers_for_work_that_isn_t_theirs(self):
        from services.models import ServiceRequest

        from .pending import total

        ServiceRequest.objects.create(kind="project", name="x", mobile_number="09350000000", contact_channel="phone",
                                      title="t", description="d" * 40, level="university", need="full")
        request = type("Request", (), {"user": self.tech})()
        self.assertEqual(total(request), 0)

    def test_staff_groups_are_the_owner_s_to_fill(self):
        admin = User.objects.create_user("09120000000", PASSWORD)
        admin.groups.add(Group.objects.get(name=SITE_ADMINS_GROUP))
        self.client.force_login(admin)
        plain = User.objects.create_user("09129999999", PASSWORD)
        response = self.client.get(reverse("admin:accounts_user_change", args=[plain.pk]))
        offered = response.context["adminform"].form.fields["groups"].queryset
        for name in (TECH_ADMINS_GROUP, OFFICE_GROUP):
            self.assertNotIn(Group.objects.get(name=name), offered)
