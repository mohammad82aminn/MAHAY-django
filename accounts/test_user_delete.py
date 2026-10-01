"""
Deleting a person: allowed when nothing of the site's record goes with them; otherwise the page says
why and offers to lock the account instead. The owner's own people are the owner's to remove.
"""
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from commerce.models import Order, OrderItem
from domains.models import Domain
from products.models import Product

from .models import User
from .roles import SITE_ADMINS_GROUP

PASSWORD = "S3cure-pass!"


class DeletingAPersonTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser("09120000000", PASSWORD)
        self.customer = User.objects.create_user("09350000000", PASSWORD, first_name="علی", last_name="علوی")
        self.client.force_login(self.owner)

    def delete_url(self, user):
        return reverse("admin:accounts_user_delete", args=[user.pk])

    def order(self, status):
        return Order.objects.create(user=self.customer, total=1_500_000, status=status)

    def test_an_order_that_never_took_money_goes_with_them(self):
        failed = self.order(Order.Status.FAILED)
        page = self.client.get(self.delete_url(self.customer))
        self.assertNotContains(page, "نباید پاک شود")
        self.assertContains(page, str(failed))  # listed among what will be deleted
        self.client.post(self.delete_url(self.customer), {"post": "yes"})
        self.assertFalse(User.objects.filter(pk=self.customer.pk).exists())
        self.assertFalse(Order.objects.filter(pk=failed.pk).exists())

    def test_a_paid_order_keeps_them_and_the_page_offers_to_lock_the_account(self):
        paid = self.order(Order.Status.PAID)
        page = self.client.get(self.delete_url(self.customer))
        self.assertContains(page, "نباید پاک شود")
        self.assertContains(page, reverse("admin:accounts_user_deactivate", args=[self.customer.pk]))
        self.client.post(self.delete_url(self.customer), {"post": "yes"})
        self.assertTrue(User.objects.filter(pk=self.customer.pk).exists())

        self.client.post(reverse("admin:accounts_user_deactivate", args=[self.customer.pk]))
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertTrue(Order.objects.filter(pk=paid.pk).exists())

    def test_an_order_that_was_paid_and_then_cancelled_is_kept_too(self):
        domain = Domain.objects.create(name="FPGA", slug="fpga")
        product = Product.objects.create(product_type="course", title="دوره", slug="c", primary_domain=domain)
        order = self.order(Order.Status.PENDING)
        OrderItem.objects.create(order=order, product=product, title="دوره", price=1_500_000)
        order.mark_paid()                 # a receipt is made
        order.status = Order.Status.CANCELED
        order.save()                      # ...and voided, but kept
        self.client.post(self.delete_url(self.customer), {"post": "yes"})
        self.assertTrue(User.objects.filter(pk=self.customer.pk).exists())

    def test_locking_needs_a_real_post(self):
        self.assertEqual(self.client.get(reverse("admin:accounts_user_deactivate", args=[self.customer.pk])).status_code, 403)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)

    def test_nobody_can_lock_themselves_out(self):
        response = self.client.post(reverse("admin:accounts_user_deactivate", args=[self.owner.pk]))
        self.assertEqual(response.status_code, 403)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)

    def test_a_second_admin_cannot_remove_or_lock_the_owner_s_people(self):
        second = User.objects.create_user("09120000001", PASSWORD)
        second.groups.add(Group.objects.get(name=SITE_ADMINS_GROUP))
        third = User.objects.create_user("09120000002", PASSWORD)
        third.groups.add(Group.objects.get(name=SITE_ADMINS_GROUP))
        self.client.force_login(second)
        for target in (self.owner, third):
            with self.subTest(target=target.mobile_number):
                self.client.post(self.delete_url(target), {"post": "yes"})
                self.client.post(reverse("admin:accounts_user_deactivate", args=[target.pk]))
                target.refresh_from_db()
                self.assertTrue(target.is_active)
        self.client.post(self.delete_url(self.customer), {"post": "yes"})  # an ordinary account is theirs to remove
        self.assertFalse(User.objects.filter(pk=self.customer.pk).exists())

    def test_the_panel_has_its_own_name(self):
        self.assertContains(self.client.get(reverse("admin:index")), "پنل مدیریت MAHAY")
