"""PostgreSQL backup primitives. Credentials travel only in process environment."""
import hashlib
import os
from pathlib import Path
import subprocess
import psycopg
from psycopg import sql
from django.conf import settings
from django.core.management.base import CommandError


def connection_options(database=None):
    db = settings.DATABASES['default']
    return dict(dbname=database or db['NAME'], user=db['USER'], password=db['PASSWORD'],
                host=db['HOST'], port=db['PORT'])


def pg_tool(name, args, database=None):
    options = connection_options(database)
    env = os.environ.copy()
    env.update(PGDATABASE=options['dbname'], PGUSER=options['user'], PGPASSWORD=options['password'],
               PGHOST=options['host'], PGPORT=str(options['port']), PGCONNECT_TIMEOUT='10')
    binary = str(Path(os.environ['PG_BIN_DIR']) / name) if os.environ.get('PG_BIN_DIR') else name
    try:
        subprocess.run([binary, *args], env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise CommandError(f'{name} is not installed; set PG_BIN_DIR to PostgreSQL client binaries.') from exc
    except subprocess.CalledProcessError as exc:
        # PostgreSQL diagnostics may contain row values; never emit them to shared logs.
        raise CommandError(f'{name} failed (exit {exc.returncode}); verify client version, database permissions, disk space, and connectivity.') from exc


def archive_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def table_fingerprints(connection):
    result = {}
    with connection.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        for (table,) in cursor.fetchall():
            cursor.execute(sql.SQL("SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) FROM "
                                   "(SELECT md5(row_to_json(t)::text) AS h FROM {} t) hashes").format(sql.Identifier('public', table)))
            count, checksum = cursor.fetchone()
            result[table] = {'rows': count, 'checksum': checksum}
    return result


def connect(database=None, **kwargs):
    return psycopg.connect(**connection_options(database), connect_timeout=10, **kwargs)
