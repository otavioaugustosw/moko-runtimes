#!/usr/bin/env python3
"""Fetch pinned macOS 26 arm64 runtimes into Local; never installs a Homebrew service.
Usage: python3 'Scripts/Preparar Runtime.py' [--refresh-lock]
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / 'Local/Runtime'
LOCK = ROOT / 'Aplicativo/Configurações/Runtime.lock.json'
FORMULAE = ['mariadb@11.8', 'mariadb-connector-c', 'php@8.4']


def fetch(url, destination, digest=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        with urllib.request.urlopen(url) as response, destination.open('wb') as output:
            shutil.copyfileobj(response, output)
    if digest and hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f'checksum mismatch: {destination.name}')


def resolve(name, records):
    if name in records:
        return
    data = json.load(urllib.request.urlopen(f'https://formulae.brew.sh/api/formula/{name}.json'))
    files = data['bottle']['stable']['files']
    tag = next((tag for tag in ['arm64_tahoe', 'arm64_sequoia', 'arm64_sonoma', 'all'] if tag in files), None)
    if tag is None:
        raise RuntimeError(f'no macOS 26 compatible arm64 bottle: {name}')
    records[name] = dict(name=name, version=data['versions']['stable'], license=data['license'],
                         bottle=files[tag], source=data['urls']['stable'], dependencies=data['dependencies'])
    for dependency in data['dependencies']:
        resolve(dependency, records)


def download_bottle(record):
    bottle = record['bottle']
    url = bottle['url']
    target = CACHE / 'Downloads' / (record['name'] + '-' + bottle['sha256'] + '.tar.gz')
    if not target.exists():
        # Homebrew's public OCI registry uses an anonymous bearer token.
        repository = url.split('/v2/')[1].split('/blobs/')[0]
        auth = json.load(urllib.request.urlopen('https://ghcr.io/token?service=ghcr.io&scope=repository:'
                                                + repository + ':pull'))['token']
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + auth})
        fetch(request, target, bottle['sha256'])
    else:
        fetch(url, target, bottle['sha256'])
    marker = CACHE / 'Extracted' / bottle['sha256']
    if not marker.exists():
        with tarfile.open(target) as archive:
            for member in archive.getmembers():
                destination = CACHE / 'Cellar' / member.name
                if member.name.startswith('/') or '..' in Path(member.name).parts:
                    raise RuntimeError('unsafe archive path')
                if member.issym() or member.islnk():
                    link = Path(os.path.normpath(str(destination.parent / member.linkname)))
                    if member.linkname.startswith('/') or not link.is_relative_to(CACHE / 'Cellar'):
                        continue
                if not destination.parent.resolve().is_relative_to((CACHE / 'Cellar').resolve()):
                    raise RuntimeError('unsafe archive parent')
                archive.extract(member, CACHE / 'Cellar')
        marker.parent.mkdir(exist_ok=True)
        marker.touch()
    versions = list((CACHE / 'Cellar' / record['name']).glob(record['version'] + '*'))
    if len(versions) != 1:
        raise RuntimeError(f'ambiguous bottle root: {record["name"]}')
    return versions[0]


def dependencies(binary):
    output = subprocess.check_output(['otool', '-L', str(binary)], text=True)
    return [line.strip().split(' (')[0] for line in output.splitlines()[1:]]


def prepare(records, overrides=None, output=None, include_server=True, include_application=True):
    roots = {name: download_bottle(record) for name, record in records.items()}
    roots.update(overrides or {})
    output = output or CACHE / 'Payload'
    if output.exists():
        shutil.rmtree(output)
    frameworks = output / 'Frameworks'
    resources = output / 'Resources/Runtime'
    frameworks.mkdir(parents=True)
    resources.mkdir(parents=True)
    server = roots.get('mariadb@11.8')
    for folder in (['bin', 'share', 'lib', 'scripts', 'support-files'] if include_server else []):
        source = server / folder
        if source.exists():
            shutil.copytree(source, resources / 'MariaDB' / folder, symlinks=True)
    if include_server:
        installer_link = resources / 'MariaDB/bin/mariadb-install-db'
        if not installer_link.is_symlink():
            installer_link.symlink_to('../scripts/mariadb-install-db')
        installer = resources / 'MariaDB/scripts/mariadb-install-db'
        installer.write_text(installer.read_text().replace('$basedir/bin $basedir/extra',
                                                           '"$basedir/bin" "$basedir/extra"'))
    postgres = (overrides or {}).get('libpq')
    if postgres:
        for folder in ['bin', 'share', 'lib']:
            shutil.copytree(postgres / folder, resources / 'PostgreSQL' / folder, symlinks=True)
        shutil.copytree(postgres / 'include', output / 'Headers/PostgreSQL')
    client = None
    connector_plugins = None
    if include_application:
        php = resources / 'PHP/bin/php'
        php.parent.mkdir(parents=True)
        shutil.copy2(roots['php@8.4'] / 'bin/php', php)
        shutil.copytree(roots['mariadb-connector-c'] / 'include', output / 'Headers', dirs_exist_ok=True)
        client = roots['mariadb-connector-c'] / 'lib/mariadb/libmariadb.3.dylib'
        if not client.exists():
            client = roots['mariadb-connector-c'] / 'lib/libmariadb.3.dylib'
        connector_plugins = roots['mariadb-connector-c'] / 'lib/mariadb/plugin'
        if not connector_plugins.exists():
            connector_plugins = roots['mariadb-connector-c'] / 'lib/plugin'
        shutil.copytree(connector_plugins, resources / 'Connector/lib/plugin', symlinks=True)
    library_sources = {}
    pending = [path for path in resources.rglob('*') if path.is_file() and not path.is_symlink()]
    if client: pending.append(client)
    visited = set()
    used_components = {'ca-certificates'} if include_application else set()
    file_components = {}

    def locate(link, owner):
        link = link.replace('@@HOMEBREW_PREFIX@@', '/opt/homebrew').replace('@@HOMEBREW_CELLAR@@', '/opt/homebrew/Cellar')
        if postgres and link.startswith('/moko/runtime/postgresql/'):
            return (postgres / link.removeprefix('/moko/runtime/postgresql/')).resolve()
        if link.startswith('@rpath/'):
            name = link.removeprefix('@rpath/')
            for folder in [owner.parent, owner.parent.parent / 'lib']:
                candidate = folder / name
                if candidate.exists(): return candidate.resolve()
            raise RuntimeError(f'unresolved rpath: {link} in {owner}')
        if link.startswith('@loader_path/'):
            return (owner.parent / link.removeprefix('@loader_path/')).resolve()
        if link.startswith('/opt/homebrew/'):
            pieces = link.split('/')
            if pieces[3] == 'opt':
                name = pieces[4]
                if name not in roots:
                    raise RuntimeError(f'undeclared dependency: {name}')
                return (roots[name] / '/'.join(pieces[5:])).resolve()
            if pieces[3] == 'Cellar':
                return (CACHE / 'Cellar' / '/'.join(pieces[4:])).resolve()
        if link.startswith('/'):
            path = Path(link)
            if any(path.is_relative_to(root) for root in roots.values()):
                return path.resolve()
            if not link.startswith(('/usr/lib/', '/System/Library/')):
                raise RuntimeError(f'unresolved build-time library path: {link} in {owner}')
        return None

    while pending:
        original = pending.pop()
        if original in visited:
            continue
        visited.add(original)
        if subprocess.run(['file', str(original)], capture_output=True, text=True).stdout.find('Mach-O') < 0:
            continue
        if original.is_relative_to(resources):
            destination = original
            # Resolve loader paths against the original Cellar layout.
            if original.is_relative_to(resources / 'MariaDB'):
                owner = server / original.relative_to(resources / 'MariaDB')
            elif postgres and original.is_relative_to(resources / 'PostgreSQL'):
                owner = postgres / original.relative_to(resources / 'PostgreSQL')
            elif original.is_relative_to(resources / 'Connector'):
                owner = connector_plugins / original.name
            else:
                owner = roots['php@8.4'] / 'bin/php'
        elif include_server and original.is_relative_to(server):
            destination = resources / 'MariaDB' / original.relative_to(server)
            owner = original
            library_sources[original] = destination
        else:
            destination = frameworks / original.name
            shutil.copy2(original, destination)
            owner = original
            library_sources[original] = destination
        component = next((name for name, root in roots.items() if owner.is_relative_to(root)), None)
        if component:
            used_components.add(component)
            file_components[str(destination.relative_to(output))] = component
        if destination.suffix == '.dylib':
            subprocess.run(['install_name_tool', '-id', '@rpath/' + destination.name, str(destination)], check=True)
        for link in dependencies(owner):
            source = locate(link, owner)
            if source:
                if not source.exists():
                    raise RuntimeError(f'missing dependency: {source}')
                if include_server and source.is_relative_to(server):
                    dependency_destination = resources / 'MariaDB' / source.relative_to(server)
                else:
                    dependency_destination = frameworks / source.name
                if source not in library_sources:
                    library_sources[source] = dependency_destination
                    pending.append(source)
                relative = __import__('os').path.relpath(dependency_destination, destination.parent)
                subprocess.run(['install_name_tool', '-change', link, '@loader_path/' + relative,
                                str(destination)], check=True, capture_output=True)
        load_commands = subprocess.check_output(['otool', '-l', str(destination)], text=True).splitlines()
        for index, line in enumerate(load_commands):
            if line.strip() == 'cmd LC_RPATH':
                path = load_commands[index + 2].strip().split('path ', 1)[1].split(' (offset')[0]
                subprocess.run(['install_name_tool', '-delete_rpath', path, str(destination)],
                               check=True, capture_output=True)
        subprocess.run(['codesign', '--force', '--sign', '-', str(destination)], check=True, capture_output=True)
    if include_application:
        shutil.copy2(roots['ca-certificates'] / 'share/ca-certificates/cacert.pem', resources / 'PHP/cert.pem')
        (resources / 'PHP/php.ini').write_text('display_errors=On\nlog_errors=On\ndate.timezone=UTC\n')
        alias = frameworks / 'libmariadb.dylib'
        alias.symlink_to('libmariadb.3.dylib')
    if postgres:
        for name in ['libpq.dylib', 'libpq.5.dylib']:
            target = frameworks / name
            if not target.exists():
                target.symlink_to('../Resources/Runtime/PostgreSQL/lib/' + name)
        for archive in (resources / 'PostgreSQL/lib').rglob('*.a'):
            archive.unlink()
    notices = resources / 'Licenses'
    notices.mkdir()
    shipped_records = {name: record for name, record in records.items() if name in used_components}
    for name, record in shipped_records.items():
        folder = notices / name
        folder.mkdir()
        for pattern in ['COPYING*', 'LICENSE*', 'COPYRIGHT*', 'NOTICE*', 'LICENSING*']:
            for source in roots[name].glob(pattern):
                if source.is_file():
                    shutil.copy2(source, folder / source.name)
        (folder / 'Source.json').write_text(json.dumps(record, indent=2) + '\n')
    (resources / 'Manifest.json').write_text(json.dumps(shipped_records, indent=2) + '\n')
    (resources / 'File Components.json').write_text(json.dumps(file_components, indent=2) + '\n')
    print(f'Runtime prepared: {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-lock', action='store_true')
    args = parser.parse_args()
    if args.refresh_lock or not LOCK.exists():
        records = {}
        for name in FORMULAE:
            resolve(name, records)
        LOCK.write_text(json.dumps(records, indent=2) + '\n')
    else:
        records = json.loads(LOCK.read_text())
    prepare(records)


if __name__ == '__main__':
    main()
