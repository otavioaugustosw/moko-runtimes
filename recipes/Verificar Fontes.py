#!/usr/bin/env python3
"""Verify complete source archives against an explicit runtime inventory.
Checks pinned upstream sources, notices and build recipes.
"""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def portable(records):
    result = json.loads(json.dumps(records))
    for record in result.values():
        record.get('bottle', {}).pop('cellar', None)
    return result


def verify_source_kit(runtime, archive):
    records = json.loads((runtime / 'Manifest.json').read_text())
    prefix = 'Corresponding Source/'
    with zipfile.ZipFile(archive) as contents:
        kit_records = json.loads(contents.read(prefix + 'Runtime.lock.json'))
        if portable(records) != portable(kit_records):
            raise RuntimeError('source kit and runtime manifest differ')
        for name in ['Construir Runtimes.py', 'Preparar Runtime.py', 'Montar Runtime.py', 'Dividir Runtime.py',
                     'Build Tools.json', 'BUILDING.md', 'Runtime Recipes License.txt', 'Legal/MPL-2.0.txt']:
            if prefix + name not in contents.namelist():
                raise RuntimeError('source kit is incomplete: ' + name)
        for name, record in records.items():
            source = prefix + name + '/upstream-' + record['version'] + '.tar.gz'
            for required in [source, prefix + name + '/Homebrew Formula.rb', prefix + name + '/Source.json']:
                if required not in contents.namelist():
                    raise RuntimeError('component source is incomplete: ' + required)
            expected = record['source'].get('checksum')
            if expected:
                value = hashlib.sha256()
                with contents.open(source) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        value.update(block)
                if value.hexdigest() != expected:
                    raise RuntimeError('upstream source checksum mismatch: ' + name)
        hashes = json.loads(contents.read(prefix + 'Kit Files.json'))
        for name, expected in hashes.items():
            value = hashlib.sha256()
            with contents.open(prefix + name) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    value.update(block)
            if value.hexdigest() != expected:
                raise RuntimeError('source kit file mismatch: ' + name)
    return records



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    args = parser.parse_args()
    records = verify_source_kit(args.runtime.resolve(), args.sources.resolve())
    print("Complete source kit verified:", len(records), "components")
