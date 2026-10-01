from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from content.access import can_open
from domains.models import Domain
from products.models import Product

from . import gateway
from .models import Cart, CartItem, Order, OrderItem, Purchase

PASSWORD = "S3cure-pass!"
COVER = "products/covers/test.png"


class CommerceTestCase(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(name="FPGA", slug="fpga")
        self.paid = self.make("دوره پولی", "paid-course", price=1_000_000, sale_price=800_000)
        self.free = self.make("دوره رایگان", "free-course", price=0)
        self.user = User.objects.create_user("09121111111", PASSWORD, first_name="علی")

    def make(self, title, slug, price=0, sale_price=None, **kwargs):
        return Product.objects.create(
            product_type="course", title=title, slug=slug, primary_domain=self.domain,
            price=price, sale_price=sale_price, is_published=True, cover=COVER, **kwargs,
        )

    def add(self, product, follow=False):
        return self.client.post(reverse("commerce:add_to_cart", args=[product.slug]), follow=follow)

    def checkout(self, follow=False):
        return self.client.post(reverse("commerce:checkout"), follow=follow)

    def cart_products(self):
        response = self.client.get(reverse("commerce:cart"))
        return list(response.context["products"])


class CartTests(CommerceTestCase):
    def test_anonymous_visitor_can_fill_a_cart(self):
        self.add(self.paid)
        self.assertEqual(self.cart_products(), [self.paid])
        self.assertEqual(Cart.objects.get().user, None)

    def test_adding_twice_keeps_one(self):
        self.add(self.paid)
        response = self.add(self.paid, follow=True)
        self.assertContains(response, "از قبل در سبد خرید")
        self.assertEqual(self.cart_products(), [self.paid])

    def test_after_adding_it_only_goes_back_to_a_page_of_this_site(self):
        url = reverse("commerce:add_to_cart", args=[self.paid.slug])
        self.assertRedirects(self.client.post(url, {"next": "/products/"}), "/products/", fetch_redirect_response=False)
        for elsewhere in ("https://evil.example/", "//evil.example/"):
            with self.subTest(next=elsewhere):
                self.assertRedirects(self.client.post(url, {"next": elsewhere}), reverse("commerce:cart"))

    def test_unavailable_product_is_refused(self):
        draft = self.make("پیش‌نویس", "draft")
        draft.is_published = False
        draft.save()
        response = self.add(draft, follow=True)
        self.assertContains(response, "قابل خرید نیست")
        self.assertEqual(self.cart_products(), [])

    def test_remove_from_cart(self):
        self.add(self.paid)
        self.client.post(reverse("commerce:remove_from_cart", args=[self.paid.slug]))
        self.assertEqual(self.cart_products(), [])

    def test_cart_moves_to_the_account_after_login(self):
        self.add(self.paid)
        self.client.login(username="09121111111", password=PASSWORD)
        self.assertEqual(self.cart_products(), [self.paid])
        self.assertEqual(Cart.objects.get().user, self.user)

    def test_archived_product_disappears_from_cart(self):
        self.add(self.paid)
        self.paid.is_archived = True
        self.paid.save()
        self.assertEqual(self.cart_products(), [])

    def test_owned_product_is_not_added_again(self):
        Purchase.objects.create(user=self.user, product=self.paid)
        self.client.force_login(self.user)
        response = self.add(self.paid, follow=True)
        self.assertContains(response, "شما این محصول را دارید")
        self.assertEqual(self.cart_products(), [])

    def test_cart_count_in_header(self):
        self.add(self.paid)
        self.assertEqual(self.client.get(reverse("home")).context["cart_count"], 1)


class CheckoutTests(CommerceTestCase):
    def test_checkout_asks_for_login_and_keeps_the_cart(self):
        self.add(self.paid)
        response = self.checkout()
        self.assertIn(reverse("accounts:login"), response["Location"])
        self.assertFalse(Order.objects.exists())

        self.client.login(username="09121111111", password=PASSWORD)
        self.assertEqual(self.cart_products(), [self.paid])  # nothing lost

    def test_free_order_needs_no_gateway(self):
        self.client.force_login(self.user)
        self.add(self.free)
        response = self.checkout(follow=True)
        order = Order.objects.get()
        self.assertEqual(order.status, "paid")
        self.assertEqual(order.total, 0)
        self.assertTrue(Purchase.objects.filter(user=self.user, product=self.free).exists())
        self.assertEqual(self.cart_products(), [])
        self.assertContains(response, "رایگان")

    def test_order_freezes_the_price(self):
        self.client.force_login(self.user)
        self.add(self.paid)
        with patch("commerce.gateway.request_payment", return_value=("A123", "https://sandbox.zarinpal.com/pg/StartPay/A123")):
            self.checkout()
        order = Order.objects.get()
        self.assertEqual(order.total, 800_000)  # the sale price

        self.paid.sale_price = None
        self.paid.price = 5_000_000
        self.paid.save()
        order.refresh_from_db()
        self.assertEqual(order.total, 800_000)  # a later price change does not touch the order

    def test_products_already_owned_are_skipped(self):
        Purchase.objects.create(user=self.user, product=self.free)
        self.client.force_login(self.user)
        CartItem.objects.create(cart=Cart.objects.create(user=self.user), product=self.free)
        self.checkout()
        order = Order.objects.first()
        self.assertIsNone(order)  # nothing left to buy

    def test_empty_cart_cannot_be_checked_out(self):
        self.client.force_login(self.user)
        response = self.checkout(follow=True)
        self.assertContains(response, "خالی است")


class PaymentTests(CommerceTestCase):
    def start_payment(self):
        self.client.force_login(self.user)
        self.add(self.paid)
        with patch("commerce.gateway.request_payment", return_value=("A123", "https://gateway.test/A123")) as request_payment:
            response = self.checkout()
        self.assertEqual(response["Location"], "https://gateway.test/A123")
        request_payment.assert_called_once()
        return Order.objects.get()

    def callback(self, order, status="OK", follow=True):
        url = reverse("commerce:payment_callback")
        return self.client.get(url, {"Authority": order.authority, "Status": status}, follow=follow)

    def test_successful_payment_gives_access(self):
        order = self.start_payment()
        self.assertFalse(can_open(self.user, self.paid))  # not paid yet

        with patch("commerce.gateway.verify_payment", return_value={"ref_id": 9911, "card_pan": "6037***1234", "message": "ok"}):
            response = self.callback(order)
        order.refresh_from_db()
        self.assertEqual(order.status, "paid")
        self.assertEqual(order.reference_id, "9911")
        self.assertTrue(can_open(self.user, self.paid))  # videos and files are now open
        self.assertEqual(self.cart_products(), [])
        self.assertContains(response, "پرداخت با موفقیت")

    def test_canceled_payment_keeps_the_cart(self):
        order = self.start_payment()
        response = self.callback(order, status="NOK")
        order.refresh_from_db()
        self.assertEqual(order.status, "canceled")
        self.assertFalse(Purchase.objects.exists())
        self.assertEqual(self.cart_products(), [self.paid])  # can try again
        self.assertContains(response, "لغو شد")

    def test_failed_verification_gives_no_access(self):
        order = self.start_payment()
        with patch("commerce.gateway.verify_payment", side_effect=gateway.PaymentError("تراکنش یافت نشد")):
            response = self.callback(order)
        order.refresh_from_db()
        self.assertEqual(order.status, "failed")
        self.assertFalse(Purchase.objects.exists())
        self.assertContains(response, "تراکنش یافت نشد")

    def test_refreshing_the_callback_does_not_pay_twice(self):
        order = self.start_payment()
        with patch("commerce.gateway.verify_payment", return_value={"ref_id": 1, "card_pan": "", "message": ""}) as verify:
            self.callback(order)
            self.callback(order)  # user pressed refresh
            verify.assert_called_once()
        self.assertEqual(Purchase.objects.filter(user=self.user, product=self.paid).count(), 1)

    def test_gateway_failure_at_start_shows_a_message(self):
        self.client.force_login(self.user)
        self.add(self.paid)
        with patch("commerce.gateway.request_payment", side_effect=gateway.PaymentError("درگاه در دسترس نیست")):
            response = self.checkout(follow=True)
        self.assertEqual(Order.objects.get().status, "failed")
        self.assertContains(response, "درگاه در دسترس نیست")

    def test_unknown_authority_is_ignored(self):
        response = self.client.get(reverse("commerce:payment_callback"), {"Authority": "X", "Status": "OK"}, follow=True)
        self.assertContains(response, "پیدا نشد")


class LibraryTests(CommerceTestCase):
    def test_library_needs_login_and_shows_purchases(self):
        url = reverse("commerce:library")
        self.assertIn(reverse("accounts:login"), self.client.get(url)["Location"])

        Purchase.objects.create(user=self.user, product=self.paid)
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertContains(response, "دوره پولی")
        self.assertNotContains(response, "دوره رایگان")

    def test_buyer_keeps_access_after_the_product_leaves_the_store(self):
        Purchase.objects.create(user=self.user, product=self.paid)
        self.paid.is_archived = True
        self.paid.save()
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("commerce:library")), "دوره پولی")
        self.assertTrue(can_open(self.user, self.paid))

    def test_product_page_shows_owned_state(self):
        Purchase.objects.create(user=self.user, product=self.paid)
        self.client.force_login(self.user)
        response = self.client.get(self.paid.get_absolute_url())
        self.assertContains(response, "خریدهای من")
        self.assertNotContains(response, "افزودن به سبد خرید")

    def test_order_list_and_detail(self):
        order = Order.objects.create(user=self.user, total=800_000, status="paid")
        OrderItem.objects.create(order=order, product=self.paid, title=self.paid.title, price=800_000)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("commerce:order_list")), order.number)
        self.assertContains(self.client.get(reverse("commerce:order_detail", args=[order.number])), "دوره پولی")

    def test_other_users_order_is_hidden(self):
        other = User.objects.create_user("09129999999", PASSWORD)
        order = Order.objects.create(user=other, total=1000)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("commerce:order_detail", args=[order.number])).status_code, 404)


class GatewayTests(TestCase):
    def test_amount_is_sent_in_rial(self):
        domain = Domain.objects.create(name="FPGA", slug="fpga")
        user = User.objects.create_user("09121111111", PASSWORD)
        order = Order.objects.create(user=user, total=150_000)
        product = Product.objects.create(product_type="course", title="t", slug="t", primary_domain=domain, price=150_000)
        OrderItem.objects.create(order=order, product=product, title="t", price=150_000)

        with patch("commerce.gateway.requests.post") as post:
            post.return_value.json.return_value = {"data": {"authority": "A1"}}
            gateway.request_payment(order, "https://mahay.test/callback")
        self.assertEqual(post.call_args.kwargs["json"]["amount"], 1_500_000)  # 150,000 Toman

    def test_gateway_error_message_is_used(self):
        user = User.objects.create_user("09121111111", PASSWORD)
        order = Order.objects.create(user=user, total=1000)
        with patch("commerce.gateway.requests.post") as post:
            post.return_value.json.return_value = {"data": [], "errors": {"message": "مبلغ نامعتبر است"}}
            with self.assertRaisesMessage(gateway.PaymentError, "مبلغ نامعتبر است"):
                gateway.request_payment(order, "https://mahay.test/callback")