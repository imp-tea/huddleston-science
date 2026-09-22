from getpass import getpass
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from accounts.models import LoginBucket, User


class Command(BaseCommand):
    help = "Reset the existing administrator password through trusted server access."

    def handle(self, *args, **options):
        if not User.objects.filter(is_admin=True).exists():
            raise CommandError("No administrator exists; use bootstrap_admin.")
        password = getpass("New administrator password: ")
        if password != getpass("Repeat password: "):
            raise CommandError("Passwords do not match.")
        with transaction.atomic():
            user = User.objects.select_for_update().get(is_admin=True)
            try:
                validate_password(password, user)
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from exc
            user.set_password(password)
            user.must_change_password = False
            user.save(update_fields=["password", "must_change_password"])
            LoginBucket.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Password reset for {user.username}; login throttles cleared."))
