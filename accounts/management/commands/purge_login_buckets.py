from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from accounts.models import LoginBucket


class Command(BaseCommand):
    help = "Remove expired pseudonymous login throttle counters."

    def handle(self, *args, **options):
        count, _ = LoginBucket.objects.filter(started_at__lt=timezone.now() - timedelta(
            seconds=settings.LOGIN_WINDOW_SECONDS)).delete()
        self.stdout.write(f"Removed {count} expired counters.")
