# moko runtimes

Build recipes, corresponding sources and license notices for the runtimes used by moko.

| Component | Version | Distribution |
| --- | --- | --- |
| PostgreSQL and libpq | 18.6 | included |
| PHP | 8.4.26 | included |
| MariaDB Connector/C | 3.4.11 | included |
| MariaDB Server and utilities | 11.8.9 | optional |

For Apple Silicon Macs running macOS 26 or later.

- **Sources:** download the complete archives from [Releases](https://github.com/otavioaugustosw/moko-runtimes/releases).
- **Build instructions:** see [BUILDING.md](BUILDING.md).
- **Manifests:** exact versions, dependencies and source checksums are in `manifests`.
- **Notices:** upstream licenses and copyright notices are in `notices`.
- **Recipes:** runtime builds, library relocation, packaging and catalog signing are in `recipes`.

The release archives include the complete upstream sources, build recipes and notices. Use those archives when rebuilding a runtime; GitHub's automatically generated repository archive contains only this repository's files.

Build scripts and original documentation are MIT licensed. Each upstream component retains its own license.

Source and license inquiries: [contato@otavioaugustosw.com](mailto:contato@otavioaugustosw.com).
