import json
from pathlib import Path
import uuid
from django.core.management.base import BaseCommand, CommandError
from psycopg import sql
from scholars.backups import archive_hash, connect, pg_tool, table_fingerprints


class Command(BaseCommand):
    help = 'Restore a trusted backup into a new temporary database, compare all table checksums, then drop only that database. Requires CREATEDB.'

    def add_arguments(self, parser):
        parser.add_argument('archive', type=Path)

    def handle(self, *args, **options):
        archive = options['archive'].resolve()
        manifest_path = archive.with_suffix('.json')
        try:
            manifest = json.loads(manifest_path.read_text())
            if manifest['format'] != 1 or manifest['archive'] != archive.name or manifest['sha256'] != archive_hash(archive):
                raise CommandError('Archive checksum or manifest does not match. Restore was not attempted.')
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError('Readable archive and valid companion manifest are required.') from exc
        database = 'huddleston_restore_check_' + uuid.uuid4().hex
        created = False
        with connect(autocommit=True) as control:
            try:
                control.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(database)))
                created = True
                pg_tool('pg_restore', ['--dbname=' + database, '--exit-on-error', '--no-owner', '--no-privileges', str(archive)], database)
                with connect(database) as restored:
                    fingerprints = table_fingerprints(restored)
                    if fingerprints != manifest['tables']:
                        raise CommandError('Restored table counts/checksums differ from the backup snapshot.')
                    required = {'django_migrations', 'accounts_user', 'scholars_practicesession', 'scholars_sessionquestion', 'scholars_reviewstate'}
                    if not required.issubset(fingerprints):
                        raise CommandError('Backup is missing required application tables.')
                    # Triggers are schema objects, not rows. Verify administrator protection survived.
                    triggers = restored.execute("SELECT count(*) FROM pg_trigger WHERE tgrelid = 'accounts_user'::regclass AND NOT tgisinternal").fetchone()[0]
                    if not triggers:
                        raise CommandError('Administrator protection trigger is missing.')
                self.stdout.write(f'Restore verified: {len(fingerprints)} tables; every row count and checksum matches.')
            finally:
                if created:
                    control.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
