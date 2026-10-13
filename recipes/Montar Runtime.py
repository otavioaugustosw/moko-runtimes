#!/usr/bin/env python3
"""Assemble built, independently licensed runtimes and exact upstream notices.

Usage: python3 'Montar Runtime.py' --manifest LOCK --sources SOURCES --work BUILD_WORK --output PAYLOAD [--cache CACHE]
"""
import argparse
import hashlib
import importlib.util
import json
import shutil
import tarfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['manifest', 'sources', 'work', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--base', action='store_true', help='PostgreSQL/PHP/clients only; no MariaDB server or GPL utilities')
    parser.add_argument('--mariadb-only', action='store_true', help='standalone optional MariaDB payload')
    args = parser.parse_args()
    if args.base and args.mariadb_only: parser.error('choose only one distribution profile')
    records = json.loads(args.manifest.read_text())
    spec = importlib.util.spec_from_file_location('preparer', Path(__file__).with_name('Preparar Runtime.py'))
    preparer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preparer)
    if args.cache:
        preparer.CACHE = args.cache.resolve()
    overrides = {}
    for component in (['server'] if args.mariadb_only else ['php', 'connector'] if args.base else ['server', 'php', 'connector']):
        build = json.loads((args.work / (component + '.json')).read_text())
        overrides[build['component']] = Path(build['prefix'])
    postgres = args.work / 'postgresql.json'
    if postgres.exists() and not args.mariadb_only:
        overrides['libpq'] = Path(json.loads(postgres.read_text())['prefix'])
    preparer.prepare(records, overrides=overrides, output=args.output.resolve(), include_server=not args.base, include_application=not args.mariadb_only)
    runtime = args.output / 'Resources/Runtime'
    records = json.loads((runtime / 'Manifest.json').read_text())
    notices = runtime / 'Licenses'
    for name, record in records.items():
        archive = args.sources / name / ('upstream-' + record['version'] + '.tar.gz')
        if record['source'].get('checksum') and hashlib.sha256(archive.read_bytes()).hexdigest() != record['source']['checksum']:
            raise RuntimeError('source checksum mismatch: ' + name)
        if tarfile.is_tarfile(archive):
            with tarfile.open(archive) as contents:
                for member in contents.getmembers():
                    filename = Path(member.name).name.upper()
                    if member.isfile() and member.size < 1_000_000 and filename.startswith(
                            ('COPYING', 'LICENSE', 'COPYRIGHT', 'NOTICE', 'LICENSING')):
                        stream = contents.extractfile(member)
                        if stream:
                            (notices / name / member.name.replace('/', '__')).write_bytes(stream.read())
    legal = Path(__file__).parent.parent / 'Aplicativo/Recursos/Legal'
    if not legal.exists():
        legal = Path(__file__).parent / 'Legal'
    if 'ca-certificates' in records:
        shutil.copy2(legal / 'MPL-2.0.txt', notices / 'ca-certificates/LICENSE.txt')
        shutil.copy2(legal / 'Certificates Notice.txt', notices / 'ca-certificates/NOTICE.txt')
    if 'php@8.4' in records:
        shutil.copy2(legal / 'PHP BSD Choice.txt', notices / 'php@8.4/License Choice.txt')
    # Build-time static archives are not runtime dependencies and are not shipped.
    for archive in (runtime / 'MariaDB/lib').rglob('*.a'):
        archive.unlink()
    metadata = dict(profile='moko-local-development-v2',
                    serverTLS='OpenSSL' if args.base else 'bundled wolfSSL with MariaDB GPLv2 exception',
                    clientTLS='OpenSSL' if args.base else 'GnuTLS',
                    applicationConnector='standalone LGPL Connector/C with OpenSSL',
                    distribution='base' if args.base else 'optional-mariadb' if args.mariadb_only else 'development-with-mariadb',
                    phpModules=['pgsql', 'pdo_pgsql', 'bcmath', 'ctype', 'curl', 'date', 'dom', 'exif', 'filter', 'hash', 'intl',
                                'json', 'libxml', 'mbstring', 'mysqli', 'mysqlnd', 'openssl', 'pcntl', 'pcre',
                                'PDO', 'pdo_mysql', 'pdo_sqlite', 'session', 'SimpleXML', 'soap', 'sockets',
                                'sodium', 'SPL', 'sqlite3', 'standard', 'tokenizer', 'xml', 'xmlreader', 'xmlwriter', 'zip', 'zlib'])
    if args.mariadb_only: metadata.pop('phpModules', None)
    (runtime / 'Build Profile.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print('Assembled source-built runtime payload:', args.output)


if __name__ == '__main__':
    main()
