import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from package_release import REQUIRED, package_release


class ProductionPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        for name in REQUIRED | {'data/practice/01.json', 'accounts/migrations/0001_initial.py',
                                'accounts/__init__.py', '.env', 'research/private.json',
                                'accounts/tests.py', 'accounts/tests/helpers.py', 'classroom/test_settings.py',
                                'tests/fixture.json', 'src/app.js', 'scripts/luna_topic_pilot.py',
                                'notes.docx'}:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('committed fixture\n')
        (self.repo / 'deploy/manage').chmod(0o755)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Release test')
        self.git('config', 'user.email', 'release-test@example.invalid')
        self.git('add', '.')
        self.git('commit', '-qm', 'Fixture')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, stderr=subprocess.PIPE)

    def test_committed_allowlist_preserves_runtime_and_excludes_development_and_secrets(self):
        # A dirty runtime file and a new untracked module must not change a
        # release labeled with the committed revision.
        (self.repo / 'data/content.json').write_text('uncommitted change')
        (self.repo / 'accounts/untracked.py').write_text('uncommitted module')
        output = self.root / 'release.tar.gz'
        result = package_release(self.repo, 'HEAD', output)
        with tarfile.open(output) as archive:
            names = set(archive.getnames())
            self.assertTrue(REQUIRED <= names)
            self.assertIn('accounts/migrations/0001_initial.py', names)
            self.assertFalse(any(name.startswith(('research/', 'tests/', 'src/', '.git')) for name in names))
            for name in ['.env', 'accounts/tests.py', 'accounts/tests/helpers.py', 'classroom/test_settings.py',
                         'scripts/luna_topic_pilot.py', 'accounts/untracked.py', 'notes.docx']:
                self.assertNotIn(name, names)
            self.assertEqual(archive.extractfile('data/content.json').read(), b'committed fixture\n')
            self.assertTrue(archive.getmember('deploy/manage').mode & 0o111)
            manifest = json.load(archive.extractfile('RELEASE.json'))
            self.assertEqual(manifest['git_commit'], result['git_commit'])
            self.assertEqual(set(manifest['files']), names - {'RELEASE.json'})
            for name, expected in manifest['files'].items():
                self.assertEqual(hashlib.sha256(archive.extractfile(name).read()).hexdigest(), expected)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            package_release(self.repo, 'HEAD', output)

    def test_missing_runtime_dependency_and_committed_symlink_fail_closed(self):
        self.git('rm', 'scripts/build.py')
        self.git('commit', '-qm', 'Missing validator')
        with self.assertRaisesRegex(ValueError, 'Incomplete production source'):
            package_release(self.repo, 'HEAD', self.root / 'missing.tar.gz')
        self.git('revert', '--no-edit', 'HEAD')
        (self.repo / 'static/external.css').symlink_to(self.root / 'outside-secret')
        self.git('add', 'static/external.css')
        self.git('commit', '-qm', 'Unsafe source link')
        with self.assertRaisesRegex(ValueError, 'regular files'):
            package_release(self.repo, 'HEAD', self.root / 'symlink.tar.gz')


if __name__ == '__main__':
    unittest.main()
