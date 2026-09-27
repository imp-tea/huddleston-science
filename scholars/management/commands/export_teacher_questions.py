"""Compatibility command: export the complete database-owned bank and history."""
from .export_question_bank import Command as BankCommand


class Command(BankCommand):
    help = 'Compatibility alias for export_question_bank --history; now includes every question.'

    def handle(self, *args, **options):
        options['history'] = True
        return super().handle(*args, **options)
