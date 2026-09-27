import json
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from scholars.importer import import_content


class Command(BaseCommand):
    help = "Import study material; seed questions only into an empty bank with --seed-questions."

    def add_arguments(self, parser):
        parser.add_argument("--data-dir", default=str(settings.BASE_DIR / "data"))
        parser.add_argument("--seed-questions", action="store_true", help="Bootstrap an empty question bank once.")
        parser.add_argument("--allow-retire", action="store_true", help="Explicitly allow removals; retire records without deleting history.")

    def handle(self, *args, **options):
        try:
            counts = import_content(options["data_dir"], options["allow_retire"], seed_questions=options["seed_questions"])
        except (ValidationError, ValueError, KeyError, TypeError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(json.dumps(counts, sort_keys=True)))
