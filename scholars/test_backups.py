import io
import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from psycopg.errors import InsufficientPrivilege
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


class BackupCleanupTests(SimpleTestCase):
    def run_verification(self, *, restore_error=None, drop_error=None):
        tables = {name: {'rows': 0, 'checksum': 'empty'} for name in (
            'django_migrations', 'accounts_user', 'scholars_practicesession',
            'scholars_sessionquestion', 'scholars_reviewstate')}
        control, restored = MagicMock(), MagicMock()
        control.__enter__.return_value = control
        restored.__enter__.return_value = restored
        restored.execute.return_value.fetchone.return_value = (1,)
        queries = []
        def execute(query):
            statement = query.as_string()
            queries.append(statement)
            if statement.startswith('DROP DATABASE'):
                if not restore_error:
                    restored.__exit__.assert_called_once()
                if drop_error:
                    raise drop_error
        control.execute.side_effect = execute
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'snapshot.dump'
            archive.write_bytes(b'trusted backup')
            archive.with_suffix('.json').write_text(json.dumps(dict(
                format=1, archive=archive.name, sha256=archive_hash(archive), tables=tables)))
            command = 'scholars.management.commands.verify_database_backup.'
            with patch(command + 'connect', side_effect=[control, restored]), \
                 patch(command + 'pg_tool', side_effect=restore_error), \
                 patch(command + 'table_fingerprints', return_value=tables):
                error = None
                try:
                    call_command('verify_database_backup', str(archive), stdout=output)
                except CommandError as exc:
                    error = exc
        return queries, output.getvalue(), error

    def test_cleanup_drops_only_created_database_without_force_after_connections_close(self):
        queries, output, error = self.run_verification()
        self.assertIsNone(error)
        self.assertEqual(len(queries), 2)
        database = queries[0].split('"')[1]
        self.assertRegex(database, r'^huddleston_restore_check_[0-9a-f]{32}$')
        self.assertEqual(queries[1], f'DROP DATABASE "{database}"')
        self.assertIn('Restore verified', output)
        self.assertIn('Temporary database removed', output)

    def test_failed_restore_still_cleans_up_without_reporting_success(self):
        queries, output, error = self.run_verification(restore_error=CommandError('Restore failed'))
        self.assertEqual(str(error), 'Restore failed')
        self.assertTrue(queries[-1].startswith('DROP DATABASE'))
        self.assertNotIn('Restore verified', output)

    def test_failed_cleanup_names_temporary_database_and_does_not_report_success(self):
        queries, output, error = self.run_verification(drop_error=InsufficientPrivilege('cannot signal'))
        database = queries[0].split('"')[1]
        self.assertIn(database, str(error))
        self.assertIn('PostgreSQL administrator', str(error))
        self.assertNotIn('Restore verified', output)
