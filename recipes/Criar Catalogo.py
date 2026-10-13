#!/usr/bin/env python3
"""Prepare and sign an optional-runtime catalog; never publish or install it automatically.
Only Developer ID/notarized component packages may be listed. Private keys are never printed.
"""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def run(*args):
    subprocess.run(list(map(str, args)), check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--package-url', required=True)
    parser.add_argument('--sources-url', required=True)
    parser.add_argument('--licenses-url', required=True)
    parser.add_argument('--team-id', required=True)
    parser.add_argument('--private-key', type=Path, required=True)
    parser.add_argument('--signer', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, required=True)
    args = parser.parse_args()
    package = args.package.resolve()
    metadata = json.loads(args.metadata.read_text())
    if not metadata.get('public'):
        parser.error('an ad-hoc development component must never enter the public catalog')
    if not re.fullmatch('[A-Z0-9]{10}', args.team_id):
        parser.error('enter the Developer ID team identifier')
    for url in [args.package_url, args.sources_url, args.licenses_url]:
        if urlsplit(url).scheme != 'https' or not urlsplit(url).netloc:
            parser.error('package, source and license links must use HTTPS')
    version = metadata.get('version', '')
    if not re.fullmatch(r'11\.8\.[0-9]+', version) or metadata.get('engine') != 'mariadb' or metadata.get('architecture') != 'arm64':
        parser.error('only the initial MariaDB 11.8 arm64 compatibility line is supported')
    value = hashlib.sha256()
    with package.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    checksum = value.hexdigest()
    if checksum != metadata.get('sha256') or package.stat().st_size != metadata.get('bytes'):
        parser.error('package bytes do not match the verified component metadata')
    run('xcrun', 'stapler', 'validate', package)
    run('spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature', package)
    with tempfile.TemporaryDirectory(prefix='moko-catalog-verify-') as directory:
        mount = Path(directory) / 'mounted'
        mount.mkdir()
        run('hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', mount, package)
        try:
            requirement = ('=anchor apple generic and certificate leaf[subject.OU] = "' + args.team_id
                           + '" and certificate leaf[field.1.2.840.113635.100.6.1.13] exists')
            run('codesign', '--verify', '--deep', '--strict', '--test-requirement', requirement, mount / 'MariaDB.runtime')
        finally:
            run('hdiutil', 'detach', mount)
    destination = args.catalog.resolve()
    existing = json.loads(destination.read_text()) if destination.exists() else dict(formatVersion=1, packages=[])
    if existing.get('formatVersion') != 1:
        parser.error('the catalog format is unsupported')
    entry = dict(id='mariadb-' + version + '-arm64', engine='mariadb', version=version, compatibilityLine='11.8',
                 architecture='arm64', minimumOS='26.0', bytes=package.stat().st_size, sha256=checksum,
                 url=args.package_url, sourcesURL=args.sources_url, licensesURL=args.licenses_url, teamID=args.team_id)
    existing['packages'] = [item for item in existing['packages'] if item['id'] != entry['id']] + [entry]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='moko-catalog-sign-', dir=destination.parent) as directory:
        catalog = Path(directory) / 'catalog.json'
        signature = Path(directory) / 'catalog.sig'
        catalog.write_text(json.dumps(existing, indent=2) + '\n')
        run(args.signer.resolve(), 'sign', args.private_key.resolve(), catalog, signature)
        catalog.replace(destination)
        signature.replace(destination.with_suffix('.sig'))
    print('Verified catalog prepared. Publish both JSON and SIG together after release approval:', destination)


if __name__ == '__main__':
    main()
