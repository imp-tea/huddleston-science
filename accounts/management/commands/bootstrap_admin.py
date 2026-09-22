from getpass import getpass
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError
from accounts.models import User


class Command(BaseCommand):
    help = "Create the single administrator interactively. No default credentials."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, **options):
        if User.objects.filter(is_admin=True).exists():
            raise CommandError("Administrator already exists; use recover_admin.")
        password = getpass("Administrator password: ")
        if password != getpass("Repeat password: "):
            raise CommandError("Passwords do not match.")
        try:
            validate_password(password, User(username=options["username"]))
            User.objects.create_superuser(options["username"], password)
        except (ValidationError, IntegrityError) as exc:
            raise CommandError("Cannot create administrator: username/password invalid or administrator already exists.") from exc
        self.stdout.write(self.style.SUCCESS("Administrator created."))
