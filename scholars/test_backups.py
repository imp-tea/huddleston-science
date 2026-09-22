import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from .backups import archive_hash, pg_tool


class BackupGuardTests(SimpleTestCase):
    def test_corrupted_archive_never_connects_or_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'snapshot.dump'
            archive.write_bytes(b'original')
            archive.with_suffix('.json').write_text(json.dumps(dict(format=1, archive=archive.name, sha256=archive_hash(archive), tables={})))
            archive.write_bytes(b'corrupt')
            with patch('scholars.management.commands.verify_database_backup.connect') as connect:
                with self.assertRaisesMessage(CommandError, 'checksum'):
                    call_command('verify_database_backup', str(archive), stdout=io.StringIO())
                connect.assert_not_called()

    def test_missing_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesMessage(CommandError, 'companion manifest'):
                call_command('verify_database_backup', str(Path(directory) / 'missing.dump'))

    def test_backup_refuses_shared_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory).chmod(0o755)
            with self.assertRaisesMessage(CommandError, 'private'):
                call_command('backup_database', directory)

    def test_missing_client_binary_is_actionable(self):
        with patch('scholars.backups.subprocess.run', side_effect=FileNotFoundError):
            with self.assertRaisesMessage(CommandError, 'PG_BIN_DIR'):
                pg_tool('pg_dump', [])
