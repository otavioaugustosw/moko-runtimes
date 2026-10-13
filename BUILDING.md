# Rebuilding moko's independent runtimes

Each source kit has its own Runtime.lock.json, complete upstream archives, exact notices, build recipes and relocation changes. The base kit covers PostgreSQL, PHP, libpq and the dynamically linked LGPL MariaDB Connector/C. The optional kit covers MariaDB Server, its utilities and their dependencies. The repository ZIP is not a substitute for these corresponding-source release assets.

Requirements: Apple Silicon macOS 26+, Xcode command-line tools/SDK, Python 3.9+, CMake, make and git. Pinned dependency bottles and build tools are fetched into an explicit cache; Homebrew is not required and no system service is installed. Use a build directory without spaces or @ because upstream parser tools restrict these paths. Replace /tmp/moko-build with a writable directory of your choice.

Extract the base ZIP and enter `Corresponding Source`:

    python3 'Construir Runtimes.py' --sources . --manifest Runtime.lock.json --tools 'Build Tools.json' --work /tmp/moko-build --cache /tmp/moko-build/Cache --component postgresql
    python3 'Construir Runtimes.py' --sources . --manifest Runtime.lock.json --tools 'Build Tools.json' --work /tmp/moko-build --cache /tmp/moko-build/Cache --component php
    python3 'Construir Runtimes.py' --sources . --manifest Runtime.lock.json --tools 'Build Tools.json' --work /tmp/moko-build --cache /tmp/moko-build/Cache --component connector
    python3 'Montar Runtime.py' --manifest Runtime.lock.json --sources . --work /tmp/moko-build --cache /tmp/moko-build/Cache --output /tmp/moko-build/Base --base

PostgreSQL is configured without readline, GSSAPI, LDAP, LLVM or external procedural language runtimes. PHP includes pgsql/pdo_pgsql and mysqlnd/mysqli/pdo_mysql. Its selected module list is recorded in Build Profile.json. Extra modules require their own integration and license review.

For the optional MariaDB component, use its own kit, source and manifest:

    python3 'Construir Runtimes.py' --sources . --manifest Runtime.lock.json --tools 'Build Tools.json' --work /tmp/moko-build --cache /tmp/moko-build/Cache --component server
    python3 'Montar Runtime.py' --manifest Runtime.lock.json --sources . --work /tmp/moko-build --cache /tmp/moko-build/Cache --output /tmp/moko-build/Optional --mariadb-only
    python3 'Dividir Runtime.py' /tmp/moko-build/Optional /tmp/moko-build/Package

The optional server uses bundled wolfSSL with the MariaDB-specific GPLv2 exception. Its internal Connector/C and command-line utilities use GnuTLS. The base runtime’s LGPL Connector/C uses OpenSSL. These have different library locations and must not be merged. The full MariaDB archive includes its vendored source and notices.

Moko's runtime modifications are these scripts: local development build configuration, dynamic-library relocation, removal of build-machine rpaths, executable signing and installer path quoting. Compiler/SDK and effective commands are recorded in generated build metadata. Upstream rights and licenses remain applicable.

## Personal LGPL replacement

1. Work on a personal copy of moko.app and keep the original and data backed up. Stop only processes owned by the test copy.
2. Rebuild the compatible Connector/C using the base kit's `connector` command and assemble the base payload.
3. Replace `Contents/Frameworks/libmariadb.3.dylib` and compatible dependencies in the personal copy. Preserve its exported API and `@rpath/libmariadb.3.dylib` install name. Do not substitute the optional server's separate internal library.
4. Re-sign modified libraries and the personal outer bundle using your own identity or an ad hoc signature. An ad hoc personal copy can omit Hardened Runtime. Do not disable Gatekeeper, SIP or global trust settings. The publisher's signature cannot cover modified code. Keychain may ask to authorize the different personal identity; keep existing credentials.
5. Test the modified copy with disposable data.

Other covered LGPL components can likewise be rebuilt from their provided sources and notices. Preserve corresponding-source access and notices when redistributing covered runtimes. These instructions do not authorize using moko branding to endorse a modified app.

## Optional package and signed catalog

`recipes/Empacotar Componente.py` packages an independently assembled `MariaDB.runtime` and checks its complete corresponding-source kit. `--public` requires your Developer ID Application identity and notarytool profile; it prepares the component DMG.

`recipes/Criar Catalogo.py` accepts only a Developer ID/notarized package matching its metadata and publisher identity, then signs the catalog with the separate Ed25519 key using CatalogSigner. Never publish or commit private signing keys.

The complete upstream source snapshot is at https://github.com/otavioaugustosw/moko-runtimes/releases/tag/runtime-sources-2026-10-12. Use the attached base/optional source ZIPs, not the automatic repository archive.
