"""Package a committed revision for the Django server using an explicit allowlist.

No working-tree files, Git history, credentials, research logs, development
tests, or legacy static application are copied into the release.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    'manage.py', 'requirements.txt', 'requirements-production.txt', 'ATTRIBUTION.md',
    'DEPLOYMENT.md', 'UPDATE_DEPLOYMENT.md', 'scripts/build.py', 'scripts/typed_content.py',
    'data/typed-questions.json',
    'data/taxonomy.json', 'data/topics.json', 'data/content.json', 'data/sources.json',
    'data/topic-redirects.json', 'data/import-manifest.json',
    'deploy/Caddyfile', 'deploy/gunicorn.conf.py', 'deploy/manage',
    'deploy/production.env.example', 'deploy/huddleston.service',
    'deploy/huddleston-backup.service', 'deploy/huddleston-backup.timer',
    'deploy/huddleston-housekeeping.service', 'deploy/huddleston-housekeeping.timer',
}
REQUIRED = FILES | {
    'classroom/settings.py', 'classroom/production.py', 'classroom/wsgi.py',
    'classroom/urls.py', 'accounts/models.py', 'scholars/models.py',
    'scholars/importer.py', 'templates/base.html', 'static/classroom.css',
    'static/typed-answer.js', 'static/typed-matching.js',
}


def runtime_path(name):
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or '..' in path.parts:
        return False
    if name in FILES:
        return True
    if any(part.startswith('.') or part == '__pycache__' for part in path.parts):
        return False
    if path.parts[0] in ('accounts', 'classroom', 'scholars'):
        return (path.suffix == '.py' and 'tests' not in path.parts
                and path.name not in ('test.py', 'tests.py', 'conftest.py')
                and not path.name.startswith('test_'))
    if path.parts[:2] == ('data', 'practice'):
        return len(path.parts) == 3 and path.suffix == '.json'
    if path.parts[0] == 'templates':
        return path.suffix == '.html'
    if path.parts[0] == 'static':
        return path.suffix.lower() in {'.css', '.js', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.ico', '.woff', '.woff2'}
    return False


def package_release(repo, ref, output):
    repo, output = Path(repo), Path(output)
    revision = subprocess.check_output(
        ['git', 'rev-parse', '--verify', ref + '^{commit}'], cwd=repo, text=True).strip()
    entries = subprocess.check_output(['git', 'ls-tree', '-r', '-z', revision], cwd=repo)
    selected = []
    for entry in filter(None, entries.split(b'\0')):
        meta, name = entry.split(b'\t', 1)
        mode, kind, _ = meta.decode().split()
        name = name.decode()
        if runtime_path(name):
            if kind != 'blob' or mode not in ('100644', '100755'):
                raise ValueError(f'Release files must be regular files: {name}')
            selected.append(name)
    missing = REQUIRED - set(selected)
    if missing or not any(name.startswith('data/practice/') for name in selected):
        raise ValueError(f'Incomplete production source: {sorted(missing)}; practice data is required')
    if output.exists():
        raise ValueError('Output already exists; choose a new release filename')
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='huddleston-release-') as temporary:
        raw = Path(temporary) / 'source.tar'
        subprocess.run(['git', 'archive', '--format=tar', '--output', str(raw),
                        revision, '--', *sorted(selected)], cwd=repo, check=True)
        manifest = {'format': 1, 'git_commit': revision, 'files': {}, 'uncompressed_bytes': 0}
        with tarfile.open(raw) as source:
            members = [m for m in source.getmembers() if not m.isdir()]
            if {m.name for m in members} != set(selected) or any(not m.isfile() for m in members):
                raise ValueError('Archive contents differ from the production allowlist')
            payload = Path(temporary) / 'release.tar.gz'
            with tarfile.open(payload, 'w:gz') as release:
                for member in members:
                    data = source.extractfile(member).read()
                    manifest['files'][member.name] = hashlib.sha256(data).hexdigest()
                    manifest['uncompressed_bytes'] += len(data)
                    # Stable ownership; retain committed executable bits and timestamp.
                    member.uid = member.gid = 0
                    member.uname = member.gname = ''
                    release.addfile(member, io.BytesIO(data))
                metadata = (json.dumps(manifest, indent=2) + '\n').encode()
                member = tarfile.TarInfo('RELEASE.json')
                member.size, member.mode = len(metadata), 0o644
                release.addfile(member, io.BytesIO(metadata))
            # Exclusive creation protects an existing operator-selected archive.
            with output.open('xb') as destination:
                destination.write(payload.read_bytes())
    return {'output': str(output), 'git_commit': revision, 'files': len(selected),
            'uncompressed_bytes': manifest['uncompressed_bytes'], 'archive_bytes': output.stat().st_size,
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD', help='Committed revision to package (default: HEAD)')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(package_release(ROOT, args.ref, args.output), indent=2))
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
