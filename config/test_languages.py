"""
The site in two languages: Persian at its usual addresses, English under /en/. The admin panel
and the content (titles, pages) stay Persian.
"""
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from accounts.models import User
from commerce import views as commerce_views
from commerce.models import Order
from config.translation import can_translate
from domains.models import Domain
from products.models import Product
from products.templatetags.store import duration, money, num, toman

PASSWORD = "S3cure-pass!"


class LanguageTestCase(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(name="هوش مصنوعی", slug="ai")
        self.product = Product.objects.create(
            product_type="course", title="یادگیری ماشین", slug="ml", primary_domain=self.domain,
            price=1_500_000, is_published=True, cover="products/covers/test.png",
        )


class AddressTests(LanguageTestCase):
    def test_persian_stays_at_the_usual_address(self):
        response = self.client.get("/products/?type=course")
        self.assertContains(response, '<html lang="fa" dir="rtl"')
        self.assertContains(response, "دوره‌های آموزشی")
        self.assertContains(response, "۱٬۵۰۰٬۰۰۰ تومان")
        # The switch leads to the same page, filters kept
        self.assertContains(response, 'href="/en/products/?type=course" hreflang="en"')

    def test_english_under_en(self):
        response = self.client.get("/en/products/?type=course")
        self.assertContains(response, '<html lang="en" dir="ltr"')
        self.assertContains(response, "Courses")
        self.assertContains(response, "1,500,000 Toman")
        self.assertContains(response, 'href="/products/?type=course" hreflang="fa"')
        # Links stay in English, and the content is shown as it was written
        self.assertContains(response, 'href="/en/products/ml/"')
        self.assertContains(response, "یادگیری ماشین")

    def test_the_address_alone_decides_not_the_browser(self):
        response = self.client.get("/products/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, '<html lang="fa" dir="rtl"')

    def test_the_admin_panel_has_no_english(self):
        self.assertEqual(self.client.get("/en/admin/").status_code, 404)
        admin = User.objects.create_superuser("09120000000", PASSWORD)
        self.client.force_login(admin)
        response = self.client.get(reverse("admin:index"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, 'lang="fa"')

    def test_a_missing_english_page_is_in_english(self):
        response = self.client.get("/en/no-such-place/")
        self.assertContains(response, "Page not found", status_code=404)
        self.assertContains(response, 'href="/en/"', status_code=404)

    def test_messages_follow_the_page(self):
        with translation.override("en"):
            response = self.client.post(reverse("commerce:add_to_cart", args=[self.product.slug]), follow=True)
        self.assertContains(response, "Added to your cart.")
        self.assertEqual(response.redirect_chain[-1][0], "/en/shop/cart/")


class StoredMessageTests(LanguageTestCase):
    def test_our_own_gateway_message_is_kept_in_persian_and_shown_in_the_page_language(self):
        buyer = User.objects.create_user("09124444444", PASSWORD)
        order = Order.objects.create(user=buyer, total=1000, status="canceled",
                                     gateway_message=commerce_views.CANCELED_BY_BUYER)
        self.assertEqual(order.gateway_message, "پرداخت توسط کاربر لغو شد.")
        self.client.force_login(buyer)
        url = reverse("commerce:order_detail", args=[order.number])
        self.assertContains(self.client.get(url), "پرداخت توسط کاربر لغو شد.")
        with translation.override("en"):
            self.assertContains(self.client.get(reverse("commerce:order_detail", args=[order.number])),
                                "The payment was canceled by the buyer.")

    def test_the_banks_own_wording_is_shown_as_it_came(self):
        buyer = User.objects.create_user("09124444444", PASSWORD)
        order = Order.objects.create(user=buyer, total=1000, status="failed", gateway_message="<b>Bank says no</b>")
        self.client.force_login(buyer)
        with translation.override("en"):
            response = self.client.get(reverse("commerce:order_detail", args=[order.number]))
        self.assertContains(response, "&lt;b&gt;Bank says no&lt;/b&gt;")  # still escaped


class NumberTests(TestCase):
    def test_persian(self):
        with translation.override("fa"):
            self.assertEqual(num(1_500_000), "۱٬۵۰۰٬۰۰۰")
            self.assertEqual(toman(0), "رایگان")
            self.assertEqual(money(25_000), "۲۵٬۰۰۰ تومان")
            self.assertEqual(duration(8100), "۲ ساعت و ۱۵ دقیقه")

    def test_english(self):
        with translation.override("en"):
            self.assertEqual(num(1_500_000), "1,500,000")
            self.assertEqual(num("2026/10/05"), "2026/10/05")
            self.assertEqual(toman(0), "Free")
            self.assertEqual(money(25_000), "25,000 Toman")
            self.assertEqual(duration(60), "1 minute")
            self.assertEqual(duration(8100), "2 hours and 15 minutes")


class RosettaAccessTests(TestCase):
    def test_only_a_superuser_may_edit_the_translations(self):
        staff = User.objects.create_user("09121111111", PASSWORD, is_staff=True)
        owner = User.objects.create_superuser("09120000000", PASSWORD)
        self.assertFalse(can_translate(AnonymousUser()))
        self.assertFalse(can_translate(staff))
        self.assertTrue(can_translate(owner))
