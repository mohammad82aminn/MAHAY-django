from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import ContactMessage, Page

PASSWORD = "S3cure-pass!"


class PageTests(TestCase):
    def test_default_pages_exist_and_open(self):
        for slug in ("about", "terms", "refund", "privacy", "faq"):
            with self.subTest(slug=slug):
                page = Page.objects.get(slug=slug)
                self.assertContains(self.client.get(page.get_absolute_url()), page.title)

    def test_unpublished_page_is_hidden(self):
        page = Page.objects.get(slug="about")
        page.is_published = False
        page.save()
        self.assertEqual(self.client.get(page.get_absolute_url()).status_code, 404)

    def test_footer_lists_the_pages(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "قوانین و مقررات")
        self.assertContains(response, "تماس با ما")

    def test_page_hidden_from_footer_still_opens(self):
        page = Page.objects.get(slug="faq")
        page.show_in_footer = False
        page.save()
        self.assertNotContains(self.client.get(reverse("home")), "پرسش‌های پرتکرار")
        self.assertEqual(self.client.get(page.get_absolute_url()).status_code, 200)

    def test_page_urls_do_not_shadow_other_sections(self):
        self.assertEqual(self.client.get(reverse("products:list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("commerce:cart")).status_code, 200)


class ContactTests(TestCase):
    url = reverse("pages:contact")

    def send(self, **changes):
        data = {
            "name": "علی رضایی", "mobile_number": "09121234567", "email": "",
            "subject": "سؤال درباره‌ی دوره", "body": "سلام، این دوره پیش‌نیاز دارد؟",
        }
        data.update(changes)
        return self.client.post(self.url, data, follow=True)

    def test_message_is_saved(self):
        response = self.send()
        self.assertContains(response, "پیام شما ثبت شد")
        message = ContactMessage.objects.get()
        self.assertEqual(message.mobile_number, "+989121234567")  # normalized
        self.assertFalse(message.is_handled)

    def test_a_way_to_answer_is_required(self):
        response = self.send(mobile_number="", email="")
        self.assertContains(response, "شماره تماس یا ایمیل")
        self.assertFalse(ContactMessage.objects.exists())

    def test_email_only_is_enough(self):
        self.send(mobile_number="", email="ali@example.com")
        self.assertEqual(ContactMessage.objects.get().email, "ali@example.com")

    def test_invalid_mobile_is_refused(self):
        response = self.send(mobile_number="12345")
        self.assertContains(response, "شماره موبایل معتبر نیست")
        self.assertFalse(ContactMessage.objects.exists())

    def test_form_is_prefilled_for_logged_in_users(self):
        user = User.objects.create_user("09121234567", PASSWORD, first_name="علی", last_name="رضایی")
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.context["form"].initial["name"], "علی رضایی")