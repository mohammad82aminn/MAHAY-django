import shutil
import tempfile

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from accounts.roles import SITE_ADMINS_GROUP, TECH_ADMINS_GROUP
from domains.models import Domain

from . import services
from .forms import ComposeForm
from .models import Delivery, Message

PASSWORD = "S3cure-pass!"
TEMP_PROTECTED = tempfile.mkdtemp()


@override_settings(PROTECTED_MEDIA_ROOT=TEMP_PROTECTED)
class InboxTestCase(TestCase):
    def setUp(self):
        self.ai = Domain.objects.create(name="هوش مصنوعی", slug="ai")
        self.power = Domain.objects.create(name="برق", slug="power")

        self.admin = self.staff_member("09120000000", "مدیر", Group.objects.get(name=SITE_ADMINS_GROUP))
        self.ali = self.staff_member("09121111111", "علی", self.ai.group)
        self.sara = self.staff_member("09122222222", "سارا", self.ai.group)
        self.reza = self.staff_member("09123333333", "رضا", self.power.group)

        self.customer = User.objects.create_user("09124444444", PASSWORD, first_name="مشتری")

    @staticmethod
    def staff_member(number, name, *groups):
        user = User.objects.create_user(number, PASSWORD, first_name=name)
        user.groups.add(*groups)
        # is_staff is set by a signal through a queryset update, which leaves this copy stale
        user.refresh_from_db()
        return user

    def send_to(self, *people, sender=None, subject="یک پیام"):
        return services.send(sender or self.admin, subject, "متن پیام", list(people))


class AccessTests(InboxTestCase):
    def test_a_customer_has_no_inbox(self):
        self.assertFalse(services.has_inbox(self.customer))

    def test_everyone_with_a_role_has_an_inbox(self):
        for person in (self.admin, self.ali, self.reza):
            with self.subTest(person=person.first_name):
                self.assertTrue(services.has_inbox(person))

    def test_a_stranger_cannot_read_the_message(self):
        message = self.send_to(self.ali)
        self.assertTrue(services.can_read(self.ali, message))
        self.assertTrue(services.can_read(self.admin, message))  # the sender
        self.assertFalse(services.can_read(self.reza, message))

    def test_a_site_admin_cannot_read_other_peoples_messages(self):
        # The full-access groups hold every permission of the site; the inbox must still be private.
        other_admin = User.objects.create_user("09125555555", PASSWORD, first_name="فنی")
        other_admin.groups.add(Group.objects.get(name=TECH_ADMINS_GROUP))
        message = services.send(self.ali, "خصوصی", "متن", [self.sara])

        self.assertFalse(services.can_read(other_admin, message))
        self.assertNotIn(message, services.visible_messages(other_admin))

    def test_someone_dropped_from_every_group_loses_the_inbox(self):
        self.send_to(self.ali)
        self.ali.groups.clear()
        self.ali.refresh_from_db()
        self.assertFalse(services.has_inbox(self.ali))

    def test_moving_between_domains_keeps_the_inbox(self):
        message = self.send_to(self.ali)
        self.ali.groups.remove(self.ai.group)
        self.ali.groups.add(self.power.group)
        self.ali.refresh_from_db()

        self.assertTrue(services.has_inbox(self.ali))
        self.assertTrue(services.can_read(self.ali, message))

    def test_the_other_side_keeps_its_copy(self):
        message = services.send(self.ali, "گزارش", "متن", [self.sara])
        self.ali.groups.clear()

        self.assertTrue(services.can_read(self.sara, message))
        self.assertEqual(Message.objects.filter(pk=message.pk).count(), 1)


class SendingTests(InboxTestCase):
    def test_a_group_is_expanded_into_its_members(self):
        people = services.resolve_recipients(groups=[self.ai.group], exclude=self.admin)
        self.assertCountEqual(people, [self.ali, self.sara])

    def test_a_later_arrival_does_not_see_an_older_message(self):
        message = services.send(
            self.admin, "اطلاعیه", "متن",
            services.resolve_recipients(groups=[self.ai.group], exclude=self.admin),
        )
        newcomer = User.objects.create_user("09126666666", PASSWORD, first_name="تازه‌وارد")
        newcomer.groups.add(self.ai.group)

        self.assertFalse(services.can_read(newcomer, message))

    def test_everyone_reaches_all_roles_but_not_customers(self):
        people = services.resolve_recipients(everyone=True, exclude=self.admin)
        self.assertCountEqual(people, [self.ali, self.sara, self.reza])

    def test_the_sender_is_never_a_recipient_of_their_own_message(self):
        people = services.resolve_recipients(groups=[self.ai.group], exclude=self.ali)
        self.assertEqual(people, [self.sara])

    def test_each_recipient_gets_their_own_copy(self):
        self.send_to(self.ali, self.sara)
        self.assertEqual(Delivery.objects.count(), 2)
        self.assertEqual(Delivery.objects.filter(read_at__isnull=True).count(), 2)


class ReadStateTests(InboxTestCase):
    def test_reading_by_one_person_leaves_it_unread_for_the_other(self):
        self.send_to(self.ali, self.sara)
        Delivery.objects.get(user=self.ali).mark_read()

        self.assertEqual(services.unread_count(self.ali), 0)
        self.assertEqual(services.unread_count(self.sara), 1)

    def test_archiving_takes_it_out_of_the_badge(self):
        from django.utils import timezone

        self.send_to(self.ali)
        self.assertEqual(services.unread_count(self.ali), 1)

        Delivery.objects.filter(user=self.ali).update(archived_at=timezone.now())
        self.assertEqual(services.unread_count(self.ali), 0)

    def test_archiving_one_side_leaves_the_other_untouched(self):
        from django.utils import timezone

        message = self.send_to(self.ali)
        Message.objects.filter(pk=message.pk).update(sender_archived_at=timezone.now())

        self.assertEqual(services.received(self.ali).count(), 1)
        self.assertEqual(services.sent(self.admin).count(), 0)
        self.assertEqual(services.sent(self.admin, archived=True).count(), 1)


class PageTests(InboxTestCase):
    """
    The access rules are proved above against the service layer; these prove the pages actually
    go through it, since a view that forgets to is exactly how a leak would appear.
    """

    inbox_url = reverse("admin:inbox_message_changelist")

    def test_a_customer_is_turned_away(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(self.inbox_url).status_code, 302)

    def test_a_recipient_sees_the_message_and_opening_it_marks_it_read(self):
        message = self.send_to(self.ali)
        self.client.force_login(self.ali)

        response = self.client.get(self.inbox_url)
        self.assertContains(response, message.subject)
        self.assertEqual(services.unread_count(self.ali), 1)

        self.client.get(reverse("admin:inbox_message_detail", args=[message.pk]))
        self.assertEqual(services.unread_count(self.ali), 0)

    def test_an_outsider_gets_a_404_not_a_403(self):
        # 403 would confirm the message exists; 404 gives nothing away
        message = self.send_to(self.ali)
        self.client.force_login(self.reza)
        response = self.client.get(reverse("admin:inbox_message_detail", args=[message.pk]))
        self.assertEqual(response.status_code, 404)

    def test_the_site_owner_cannot_open_someone_elses_message(self):
        owner = User.objects.create_superuser("09129999999", PASSWORD, first_name="مالک")
        message = services.send(self.ali, "خصوصی", "متن", [self.sara])

        self.client.force_login(owner)
        response = self.client.get(reverse("admin:inbox_message_detail", args=[message.pk]))
        self.assertEqual(response.status_code, 404)

    def test_an_outsider_cannot_download_the_attachment(self):
        message = self.send_to(self.ali)
        attachment = message.files.create(file=SimpleUploadedFile("spec.pdf", b"%PDF-1.4"))
        url = reverse("admin:inbox_message_file", args=[attachment.pk])

        self.client.force_login(self.reza)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.ali)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_sending_to_a_group_from_the_page(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("admin:inbox_message_compose"), {
            "subject": "اطلاعیه", "body": "متن اطلاعیه", "to_groups": [self.ai.group.pk],
        })
        message = Message.objects.get(subject="اطلاعیه")
        self.assertCountEqual([d.user for d in message.deliveries.all()], [self.ali, self.sara])

    def test_a_message_with_no_recipient_is_refused(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin:inbox_message_compose"), {
            "subject": "بی‌گیرنده", "body": "متن",
        })
        self.assertContains(response, "دست‌کم یک گیرنده")
        self.assertFalse(Message.objects.filter(subject="بی‌گیرنده").exists())

    def test_archiving_hides_it_from_the_owner_only(self):
        message = self.send_to(self.ali, self.sara)
        self.client.force_login(self.ali)
        self.client.post(reverse("admin:inbox_message_archive", args=[message.pk]))

        self.assertEqual(services.received(self.ali).count(), 0)
        self.assertEqual(services.received(self.sara).count(), 1)

    def test_the_badge_costs_nothing_for_someone_without_a_role(self):
        from inbox.context_processors import unread

        request = type("R", (), {"user": self.customer})()
        self.assertEqual(unread(request), {})

    def test_replying_never_asks_who_it_goes_to(self):
        message = services.send(self.admin, "نماز", "متن", [self.ali])
        self.client.force_login(self.ali)

        response = self.client.get(reverse("admin:inbox_message_reply", args=[message.pk]))
        self.assertNotContains(response, "name=\"to_users\"")
        self.assertNotContains(response, "name=\"to_groups\"")
        self.assertContains(response, self.admin.get_full_name())

    def test_a_reply_reaches_the_original_sender(self):
        message = services.send(self.admin, "نماز", "متن", [self.ali])
        self.client.force_login(self.ali)

        self.client.post(reverse("admin:inbox_message_reply", args=[message.pk]),
                         {"subject": "پاسخ: نماز", "body": "تذکر داده می‌شود"})
        reply = Message.objects.get(subject="پاسخ: نماز")
        self.assertEqual([d.user for d in reply.deliveries.all()], [self.admin])
        self.assertEqual(reply.parent, message)

    def test_the_site_owner_can_be_written_to(self):
        # A superuser belongs to no group but still has an inbox, so they must be reachable —
        # otherwise nobody can answer the person who sends most of the messages.
        owner = User.objects.create_superuser("09129999999", PASSWORD, first_name="مالک")
        self.assertTrue(services.has_inbox(owner))
        self.assertIn(owner, services.addressable_users())
        self.assertIn(owner, services.resolve_recipients(everyone=True, exclude=self.ali))

    def test_the_recipient_picker_never_shows_a_phone_number(self):
        nameless = self.staff_member("09127777777", "")
        nameless.groups.add(self.ai.group)
        form = ComposeForm(sender=self.admin)
        labels = [str(label) for _value, label in form.fields["to_users"].choices]

        self.assertFalse(any(nameless.mobile_number in label for label in labels))


def tearDownModule():
    shutil.rmtree(TEMP_PROTECTED, ignore_errors=True)
