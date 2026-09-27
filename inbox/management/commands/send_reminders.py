from django.core.management.base import BaseCommand

from inbox import reminders


class Command(BaseCommand):
    help = "یادآوری کارهایی که بیش از ۴۸ ساعت منتظر مانده‌اند (هر ساعت با cron اجرا شود)."

    def handle(self, *args, **options):
        sent = reminders.send_due()
        self.stdout.write(f"{sent} message(s) sent.")
