#!/usr/bin/env python3
"""Package the independent MariaDB component. Public mode requires Developer ID and notarization.
Usage: python3 'Scripts/Empacotar Componente.py' --runtime PATH --sources ZIP --output DMG
"""
import argparse
import hashlib
import importlib.util
import json
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*args):
    subprocess.run(list(map(str, args)), check=True, capture_output=True)


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--public', action='store_true')
    parser.add_argument('--identity')
    parser.add_argument('--notary-profile')
    args = parser.parse_args()
    original, output = args.runtime.resolve(), args.output.resolve()
    info = plistlib.loads((original / 'Contents/Info.plist').read_bytes())
    version = info['CFBundleShortVersionString']
    if info.get('CFBundlePackageType') != 'BNDL' or not version.startswith('11.8.'):
        parser.error('only the MariaDB 11.8 component bundle is supported by this recipe')
    runtime = original / 'Contents/Resources/Runtime'
    spec = importlib.util.spec_from_file_location('release_gates', Path(__file__).with_name('Verificar Fontes.py'))
    gates = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gates)
    records = gates.verify_source_kit(runtime, args.sources.resolve())
    if 'mariadb@11.8' not in records or 'libpq' in records or 'php@8.4' in records:
        parser.error('the optional inventory must be independent of the PostgreSQL/PHP base')
    if args.public and (not args.identity or not args.identity.startswith('Developer ID Application:') or not args.notary_profile):
        parser.error('public packaging requires Developer ID Application and a notarytool keychain profile')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='moko-mariadb-package-') as directory:
        staging = Path(directory)
        bundle = staging / 'MariaDB.runtime'
        shutil.copytree(original, bundle, symlinks=True)
        for file in bundle.rglob('*'):
            if not file.is_file() or file.is_symlink():
                continue
            with file.open('rb') as stream:
                header = stream.read(8)
            if header[:4] == b'\xcf\xfa\xed\xfe':
                if header[4:] != b'\x0c\0\0\x01':
                    raise RuntimeError('unsupported architecture: ' + str(file.relative_to(bundle)))
                run('codesign', '--force', '--sign', args.identity if args.public else '-', '--options', 'runtime',
                    '--timestamp' if args.public else '--timestamp=none', file)
        run('codesign', '--force', '--sign', args.identity if args.public else '-', '--options', 'runtime',
            '--timestamp' if args.public else '--timestamp=none', bundle)
        run('codesign', '--verify', '--deep', '--strict', bundle)
        if not args.public:
            (staging / 'Development Build.txt').write_text('Unsigned-publication candidate only. Not notarized. Do not distribute as an installable release.\n')
        (staging / 'Read Me.txt').write_text(
            'Optional independent MariaDB runtime for moko. Install from settings → components.\n'
            'Do not copy this component into the signed moko app. Data is stored separately.\n'
            'Corresponding sources and notices are available in the release containing this package.\n')
        candidate = output.with_name(output.stem + '.staging.dmg')
        candidate.unlink(missing_ok=True)
        try:
            run('diskutil', 'image', 'create', 'from', '--volumeName', 'moko mariadb ' + version,
                '--format', 'UDZO', staging, candidate)
            if args.public:
                run('codesign', '--sign', args.identity, '--timestamp', candidate)
                run('xcrun', 'notarytool', 'submit', candidate, '--keychain-profile', args.notary_profile, '--wait')
                run('xcrun', 'stapler', 'staple', candidate)
                run('xcrun', 'stapler', 'validate', candidate)
                run('spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature', candidate)
            run('hdiutil', 'verify', candidate)
            candidate.replace(output)
        finally:
            candidate.unlink(missing_ok=True)
    metadata = dict(engine='mariadb', version=version, compatibilityLine='11.8', architecture='arm64', minimumOS='26.0',
                    bytes=output.stat().st_size, sha256=digest(output), public=args.public)
    output.with_suffix('.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print('Component package verified:', output)
    if not args.public:
        print('Development candidate only; the production installer must reject this ad-hoc signature.')


if __name__ == '__main__':
    main()
