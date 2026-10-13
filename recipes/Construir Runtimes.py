#!/usr/bin/env python3
"""Build the selected local-development runtimes from verified source.

No system service or database is installed. Build products stay inside --work.
Usage: python3 'Construir Runtimes.py' --sources SOURCE_KIT --manifest LOCK --work WORK [--component server|php|connector]
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import shlex
import subprocess
import tarfile
from pathlib import Path


def run(arguments, cwd=None, environment=None):
    print('Running:', arguments[0], flush=True)
    subprocess.run(list(map(str, arguments)), cwd=cwd, env=environment, check=True)


def source(folder, record, work):
    archive = folder / ('upstream-' + record['version'] + '.tar.gz')
    expected = record['source'].get('checksum')
    if expected and hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError('source checksum mismatch: ' + record['name'])
    destination = work / 'Sources' / record['name'].replace('@', '-')
    if not (destination / '.extracted').exists():
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as contents:
            for member in contents.getmembers():
                if member.name.startswith('/') or '..' in Path(member.name).parts:
                    raise RuntimeError('unsafe source path')
                if member.issym() or member.islnk():
                    parent = destination / Path(member.name).parent if member.issym() else destination
                    target = Path(os.path.normpath(str(parent / member.linkname)))
                    if member.linkname.startswith('/') or not target.is_relative_to(destination):
                        raise RuntimeError('unsafe source symlink')
            contents.extractall(destination)
        (destination / '.extracted').touch()
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise RuntimeError('ambiguous source tree')
    return roots[0]


def environment(work):
    result = dict(os.environ)
    sdk = subprocess.check_output(['xcrun', '--show-sdk-path'], text=True).strip()
    result.update(MACOSX_DEPLOYMENT_TARGET='26.0', SDKROOT=sdk)
    result['CFLAGS'] = '-O2 -mmacosx-version-min=26.0 ' + shlex.quote('-ffile-prefix-map=' + str(work) + '=/moko-runtime')
    result['CXXFLAGS'] = result['CFLAGS']
    return result


def server(tree, work, jobs, env, dependencies):
    build, prefix = work / 'Build/server-wolfssl', work / 'Install/server'
    args = ['cmake', '-S', tree, '-B', build, '-DCMAKE_BUILD_TYPE=Release',
            '-DCMAKE_POLICY_VERSION_MINIMUM=3.5', '-DCMAKE_OSX_DEPLOYMENT_TARGET=26.0',
            '-DCMAKE_OSX_ARCHITECTURES=arm64', '-DCMAKE_INSTALL_PREFIX=' + str(prefix),
            '-DWITH_SSL=bundled', '-DWITH_ZLIB=bundled', '-DWITH_PCRE=bundled', '-DWITH_LIBFMT=bundled',
            '-DCONC_WITH_SSL=GNUTLS', '-DGNUTLS_LIBRARY=' + str(dependencies['gnutls'] / 'lib/libgnutls.dylib'),
            '-DGNUTLS_INCLUDE_DIR=' + str(dependencies['gnutls'] / 'include'),
            '-DCONC_AUTH_GSSAPI_PLUGIN_TYPE=OFF',
            '-DWITH_UNIT_TESTS=OFF', '-DWITH_EMBEDDED_SERVER=OFF', '-DWITH_WSREP=OFF',
            '-DWITH_JEMALLOC=OFF', '-DWITH_READLINE=OFF', '-DCONNECT_WITH_JDBC=OFF',
            '-DPLUGIN_MROONGA=NO', '-DPLUGIN_ROCKSDB=NO', '-DPLUGIN_CONNECT=NO',
            '-DPLUGIN_SPIDER=NO', '-DPLUGIN_OQGRAPH=NO', '-DPLUGIN_S3=NO',
            '-DPLUGIN_COLUMNSTORE=NO', '-DPLUGIN_AUTH_GSSAPI=NO',
            '-DPLUGIN_PROVIDER_LZO=NO', '-DPLUGIN_PROVIDER_LZMA=NO', '-DPLUGIN_PROVIDER_LZ4=NO',
            '-DPLUGIN_PROVIDER_BZIP2=NO', '-DPLUGIN_PROVIDER_SNAPPY=NO',
            '-DDEFAULT_CHARSET=utf8mb4', '-DDEFAULT_COLLATION=utf8mb4_unicode_ci',
            '-DWITH_DTRACE=OFF', '-DENABLE_DTRACE=OFF']
    run(args, environment=env)
    run(['cmake', '--build', build, '--parallel', jobs], environment=env)
    run(['cmake', '--install', build], environment=env)
    return prefix, args


def package_environment(work, env, dependencies):
    pkg = work / 'Pkgconfig'
    pkg.mkdir(exist_ok=True)
    for name, root in dependencies.items():
        for path in (root / 'lib/pkgconfig').glob('*.pc'):
            text = path.read_text().replace('@@HOMEBREW_PREFIX@@', '/opt/homebrew').replace(
                '@@HOMEBREW_CELLAR@@', '/opt/homebrew/Cellar')
            for dependency, prefix in dependencies.items():
                text = text.replace('/opt/homebrew/opt/' + dependency, str(prefix))
                text = text.replace('/opt/homebrew/Cellar/' + dependency + '/' + prefix.resolve().name, str(prefix))
            (pkg / path.name).write_text(text)
    sdk = env['SDKROOT']
    (pkg / 'libxml-2.0.pc').write_text(
        'Name: libXML\nDescription: macOS SDK XML library\nVersion: 2.14.0\n'
        'Libs: -lxml2\nCflags: -I' + sdk + '/usr/include/libxml2\n')
    return dict(env, PKG_CONFIG_PATH=str(pkg))


def php(tree, work, jobs, env, dependencies):
    build = work / 'Build/php'
    build.mkdir(parents=True, exist_ok=True)
    env = package_environment(work, env, dependencies)
    # A fixed virtual prefix prevents personal build paths from becoming runtime defaults.
    args = [tree / 'configure', '--prefix=/moko/runtime/php', '--disable-all', '--enable-cli',
            '--disable-cgi', '--disable-phpdbg', '--without-pear',
            '--with-config-file-path=/moko/runtime/php', '--with-config-file-scan-dir=',
            '--enable-filter', '--enable-tokenizer', '--enable-session', '--enable-ctype',
            '--enable-pdo', '--enable-mysqlnd', '--with-mysqli=mysqlnd', '--with-pdo-mysql=mysqlnd',
            '--with-pdo-sqlite', '--with-sqlite3', '--with-pdo-pgsql', '--with-pgsql',
            '--with-openssl', '--with-curl', '--with-zlib',
            '--enable-mbstring', '--enable-mbregex', '--enable-intl', '--with-zip',
            '--with-sodium', '--with-password-argon2', '--enable-bcmath', '--enable-exif',
            '--enable-pcntl', '--enable-sockets', '--enable-opcache',
            '--with-libxml', '--enable-dom', '--enable-simplexml', '--enable-xml',
            '--enable-xmlreader', '--enable-xmlwriter', '--enable-soap']
    run(args, cwd=build, environment=env)
    run(['make', '-j' + str(jobs)], cwd=build, environment=env)
    stage = work / 'Install/php-stage'
    run(['make', 'INSTALL_ROOT=' + str(stage), 'install'], cwd=build, environment=env)
    return stage / 'moko/runtime/php', args


def postgresql(tree, work, jobs, env, dependencies):
    build = work / 'Build/postgresql'
    build.mkdir(parents=True, exist_ok=True)
    env = package_environment(work, env, dependencies)
    env['CPPFLAGS'] = '-I' + str(dependencies['openssl@4'] / 'include') + ' -I' + str(dependencies['icu4c@78'] / 'include')
    env['LDFLAGS'] = '-L' + str(dependencies['openssl@4'] / 'lib') + ' -L' + str(dependencies['icu4c@78'] / 'lib')
    args = [tree / 'configure', '--prefix=/moko/runtime/postgresql', '--without-readline',
            '--without-ldap', '--without-gssapi', '--with-openssl', '--with-icu', '--with-libxml',
            '--without-perl', '--without-python', '--without-tcl', '--without-llvm']
    run(args, cwd=build, environment=env)
    run(['make', '-j' + str(jobs)], cwd=build, environment=env)
    stage = work / 'Install/postgresql-stage'
    run(['make', 'DESTDIR=' + str(stage), 'install'], cwd=build, environment=env)
    return stage / 'moko/runtime/postgresql', args


def connector(tree, work, jobs, env, dependencies):
    build, prefix = work / 'Build/connector', work / 'Install/connector'
    args = ['cmake', '-S', tree, '-B', build, '-DCMAKE_BUILD_TYPE=Release',
            '-DCMAKE_POLICY_VERSION_MINIMUM=3.5', '-DCMAKE_OSX_DEPLOYMENT_TARGET=26.0',
            '-DCMAKE_INSTALL_PREFIX=' + str(prefix), '-DINSTALL_LIBDIR=lib',
            '-DWITH_UNIT_TESTS=OFF', '-DWITH_EXTERNAL_ZLIB=ON', '-DWITH_SSL=OPENSSL',
            '-DOPENSSL_ROOT_DIR=' + str(dependencies['openssl@4']),
            '-DAUTH_GSSAPI_PLUGIN_TYPE=OFF', '-DREMOTEIO_PLUGIN_TYPE=OFF']
    run(args, environment=env)
    run(['cmake', '--build', build, '--parallel', jobs], environment=env)
    run(['cmake', '--install', build], environment=env)
    return prefix, args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--tools', type=Path)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--component', choices=['server', 'php', 'connector', 'postgresql'], required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    records = json.loads(args.manifest.read_text())
    spec = importlib.util.spec_from_file_location('runtime_preparer', Path(__file__).with_name('Preparar Runtime.py'))
    preparer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preparer)
    if args.cache:
        preparer.CACHE = args.cache.resolve()
    if args.component == 'server' and 'gnutls' not in records:
        preparer.resolve('gnutls', records)
        args.manifest.write_text(json.dumps(records, indent=2) + '\n')
    dependencies = {name: preparer.download_bottle(record) for name, record in records.items()}
    dependency_links = work / 'Dependencies'
    dependency_links.mkdir(exist_ok=True)
    for name, prefix in list(dependencies.items()):
        link = dependency_links / name
        if not link.exists():
            link.symlink_to(prefix, target_is_directory=True)
        dependencies[name] = link
    env = environment(work)
    tool_records = json.loads(args.tools.read_text()) if args.tools else {}
    for name in ['pkgconf', 'bison']:
        if name not in tool_records:
            preparer.resolve(name, tool_records)
    tools = {name: preparer.download_bottle(record) for name, record in tool_records.items()}
    env['PATH'] = ':'.join(str(path / 'bin') for path in tools.values()) + ':' + env['PATH']
    tool_bin = work / 'ToolBin'
    tool_bin.mkdir(exist_ok=True)
    for name, executable in [('pkgconf', tools['pkgconf'] / 'bin/pkgconf'), ('bison', tools['bison'] / 'bin/bison')]:
        link = tool_bin / name
        if name == 'pkgconf':
            if link.is_symlink():
                link.unlink()
            if not link.exists():
                shutil.copy2(executable, link)
                library = tool_bin / 'libpkgconf.8.dylib'
                shutil.copy2(tools['pkgconf'] / 'lib/libpkgconf.8.dylib', library)
                run(['install_name_tool', '-id', '@loader_path/libpkgconf.8.dylib', library])
                original = preparer.dependencies(executable)[0]
                run(['install_name_tool', '-change', original, '@loader_path/libpkgconf.8.dylib', link])
                for binary in [library, link]:
                    run(['codesign', '--force', '--sign', '-', binary])
        elif not link.exists():
            link.symlink_to(executable)
    env['PATH'] = str(tool_bin) + ':' + env['PATH']
    env['PKG_CONFIG'] = str(tool_bin / 'pkgconf')
    env['DYLD_LIBRARY_PATH'] = ':'.join(str(path / 'lib') for path in [*tools.values(), *dependencies.values()])
    (work / 'Build Tools.json').write_text(json.dumps(tool_records, indent=2) + '\n')
    name = {'server': 'mariadb@11.8', 'php': 'php@8.4', 'connector': 'mariadb-connector-c', 'postgresql': 'libpq'}[args.component]
    tree = source(args.sources / name, records[name], work)
    if args.component == 'server':
        prefix, recipe = server(tree, work, args.jobs, env, dependencies)
    elif args.component == 'php':
        prefix, recipe = php(tree, work, args.jobs, env, dependencies)
    elif args.component == 'postgresql':
        prefix, recipe = postgresql(tree, work, args.jobs, env, dependencies)
    else:
        prefix, recipe = connector(tree, work, args.jobs, env, dependencies)
    metadata = dict(component=name, version=records[name]['version'], prefix=str(prefix),
                    recipe=list(map(str, recipe)), compiler=subprocess.check_output(['clang', '--version'], text=True))
    (work / (args.component + '.json')).write_text(json.dumps(metadata, indent=2) + '\n')
    print('Built', name, 'at', prefix, flush=True)


if __name__ == '__main__':
    main()
