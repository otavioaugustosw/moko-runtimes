#!/usr/bin/env python3
"""Extract only the optional MariaDB component and its dependency closure.

Usage: python3 'Scripts/Dividir Runtime.py' FULL_PAYLOAD OUTPUT_DIRECTORY
The result is MariaDB.runtime, suitable for a separately signed/notarized DMG.
"""
import argparse
import json
import plistlib
import shutil
import subprocess
from pathlib import Path


def binary(path):
    if not path.is_file() or path.is_symlink():
        return False
    with path.open('rb') as stream:
        return stream.read(4) == b'\xcf\xfa\xed\xfe'


def split(source, destination):
    if destination.exists():
        raise RuntimeError('destination already exists; preserve or remove it explicitly before rebuilding')
    root = destination / 'MariaDB.runtime/Contents'
    runtime = root / 'Resources/Runtime'
    runtime.mkdir(parents=True)
    (root / 'Frameworks').mkdir()
    source_runtime = source / 'Resources/Runtime'
    shutil.copytree(source_runtime / 'MariaDB', runtime / 'MariaDB', symlinks=True)
    components = json.loads((source_runtime / 'File Components.json').read_text())
    records = json.loads((source_runtime / 'Manifest.json').read_text())
    used = set()
    pending = [source_runtime / path.relative_to(runtime) for path in (runtime / 'MariaDB').rglob('*') if binary(path)]
    seen = set()
    inventory = {}
    while pending:
        owner = pending.pop().resolve()
        if owner in seen:
            continue
        seen.add(owner)
        relative = owner.relative_to(source)
        target = root / relative
        name = components.get(str(relative))
        if not name:
            raise RuntimeError('binary has no source attribution: ' + str(relative))
        used.add(name)
        inventory[str(relative)] = name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(owner, target)
        links = subprocess.check_output(['otool', '-L', str(owner)], text=True).splitlines()[1:]
        for entry in links:
            link = entry.strip().split(' (')[0]
            if link.startswith(('/usr/lib/', '/System/Library/', '@rpath/')):
                # @rpath is the dylib's own install ID; all dependencies were relocated to @loader_path.
                if link.startswith('@rpath/') and not owner.name == link.removeprefix('@rpath/'):
                    raise RuntimeError('unresolved runtime dependency: ' + link)
                continue
            if not link.startswith('@loader_path/'):
                raise RuntimeError('nonportable runtime dependency: ' + link)
            dependency = (owner.parent / link.removeprefix('@loader_path/')).resolve()
            if not dependency.is_relative_to(source.resolve()) or not dependency.exists():
                raise RuntimeError('dependency escapes or is missing from the runtime payload')
            pending.append(dependency)
    shipped = {name: value for name, value in records.items() if name in used}
    (runtime / 'Licenses').mkdir()
    for name in shipped:
        shutil.copytree(source_runtime / 'Licenses' / name, runtime / 'Licenses' / name)
    (runtime / 'Manifest.json').write_text(json.dumps(shipped, indent=2) + '\n')
    (runtime / 'File Components.json').write_text(json.dumps(inventory, indent=2) + '\n')
    (runtime / 'Build Profile.json').write_text(json.dumps(dict(
        profile='moko-optional-mariadb-v1', distribution='optional-mariadb',
        serverTLS='bundled wolfSSL with MariaDB GPLv2 exception', clientTLS='GnuTLS'), indent=2) + '\n')
    (root / 'Info.plist').write_bytes(plistlib.dumps(dict(
        CFBundleIdentifier='com.otavioaugustosw.moko.runtime.mariadb', CFBundleName='MariaDB.runtime',
        CFBundlePackageType='BNDL', CFBundleVersion=shipped['mariadb@11.8']['version'],
        CFBundleShortVersionString=shipped['mariadb@11.8']['version'], LSMinimumSystemVersion='26.0')))
    print('Optional MariaDB:', len(shipped), 'source-attributed components,', len(seen), 'binaries.')
    print(destination / 'MariaDB.runtime')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('payload', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    split(args.payload.resolve(), args.output.resolve())
