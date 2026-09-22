import json
import os
from pathlib import Path
import uuid
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from scholars.backups import archive_hash, connect, pg_tool, table_fingerprints


class Command(BaseCommand):
    help = 'Create a private custom-format PostgreSQL dump and snapshot-consistent verification manifest.'

    def add_arguments(self, parser):
        parser.add_argument('directory', type=Path)

    def handle(self, *args, **options):
        directory = options['directory'].resolve()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.stat().st_mode & 0o077:
            raise CommandError('Backup directory must be private (chmod 700).')
        stem = 'huddleston-' + timezone.now().strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8]
        archive = directory / (stem + '.dump')
        partial = directory / (stem + '.partial')
        manifest = directory / (stem + '.json')
        try:
            # Same read-only MVCC snapshot for the dump and every table checksum.
            with connect() as connection:
                connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                snapshot = connection.execute('SELECT pg_export_snapshot()').fetchone()[0]
                fingerprints = table_fingerprints(connection)
                descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(descriptor)
                pg_tool('pg_dump', ['--format=custom', '--no-owner', '--no-privileges', '--snapshot=' + snapshot, '--file=' + str(partial)])
            payload = dict(format=1, archive=archive.name, sha256=archive_hash(partial), tables=fingerprints,
                           created_at=timezone.now().isoformat())
            descriptor = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(payload, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            with partial.open('rb') as stream:
                os.fsync(stream.fileno())
            partial.replace(archive)
        except Exception:
            partial.unlink(missing_ok=True)
            manifest.unlink(missing_ok=True)
            raise
        self.stdout.write(f'Backup created: {archive}\nManifest: {manifest}')
