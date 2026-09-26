# Dependency and license inventory

Snapshot: 2026-09-26T09:42:52+00:00 · Python 3.13.14 · `uv.lock` SHA-256 `d060336845f823a21ddce48f33c4b37c0cb110b7b813244a1b789941d202a87f`.

This inventory records all 21 `uv.lock` package identities and the 20 distributions installed in `.venv/lib/python3.13/site-packages`. Versions in the installed environment match the corresponding lock entries. `typing-extensions==4.16.0` is locked only for Python below 3.13 through `referencing`; it is correctly absent on this Python 3.13 host. The machine-readable [inventory](dependencies.json) records each package version, lock source and source-distribution hash (where present), upstream source URL, declared license metadata, and SHA-256 of any license file bundled in the installed distribution. A metadata license claim is not a complete legal review of the source tree or binary components.

| Package | Version | Role | Declared license | Evidence | Upstream source |
| --- | --- | --- | --- | --- | --- |
| anki-pipeline | 3.0.0rc1 | project | Unknown / undeclared | Project metadata: no license declaration | Local project |
| attrs | 26.1.0 | transitive | MIT | Installed metadata + 1 bundled license file | [source](https://github.com/python-attrs/attrs) |
| cached-property | 2.0.1 | transitive | BSD | Installed metadata + 1 bundled license file | [source](https://github.com/pydanny/cached-property) |
| certifi | 2026.7.22 | transitive | MPL-2.0 | Installed metadata + 1 bundled license file | [source](https://github.com/certifi/python-certifi) |
| charset-normalizer | 3.5.1 | transitive | MIT | Installed metadata + 1 bundled license file | [source](https://github.com/jawah/charset_normalizer) |
| chevron | 0.14.0 | transitive | MIT | Installed metadata + 1 bundled license file | [source](https://github.com/noahmorrison/chevron) |
| et-xmlfile | 2.0.0 | transitive | MIT | Installed metadata only; no bundled file found | [source](https://foss.heptapod.net/openpyxl/et_xmlfile) |
| frozendict | 2.4.7 | transitive | LGPL v3 | Installed metadata + 1 bundled license file | [source](https://github.com/Marco-Sulla/python-frozendict) |
| genanki | 0.13.1 | runtime_direct | MIT | Installed metadata + 1 bundled license file | [source](http://github.com/kerrickstaley/genanki) |
| idna | 3.20 | transitive | BSD-3-Clause | Installed metadata + 1 bundled license file | [source](https://github.com/kjd/idna) |
| jsonschema | 4.25.1 | dev_direct | MIT | Installed metadata + 1 bundled license file | [source](https://github.com/python-jsonschema/jsonschema) |
| jsonschema-specifications | 2025.9.1 | transitive | MIT | Installed metadata + 1 bundled license file | [source](https://github.com/python-jsonschema/jsonschema-specifications) |
| lxml | 6.1.0 | runtime_direct | BSD-3-Clause | Installed metadata + 2 bundled license files | [source](https://github.com/lxml/lxml) |
| openpyxl | 3.1.5 | runtime_direct | MIT | Installed metadata only; no bundled file found | [source](https://foss.heptapod.net/openpyxl/openpyxl) |
| pymupdf | 1.26.3 | runtime_direct | Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License | Installed metadata + 1 bundled license file | [source](https://github.com/pymupdf/pymupdf) |
| pyyaml | 6.0.3 | transitive | MIT | Installed metadata + 1 bundled license file | [source](https://pyyaml.org/) |
| referencing | 0.37.0 | transitive | MIT | Installed metadata + 1 bundled license file | [source](https://github.com/python-jsonschema/referencing) |
| requests | 2.33.0 | runtime_direct | Apache-2.0 | Installed metadata + 2 bundled license files | [source](https://github.com/psf/requests) |
| rpds-py | 2026.6.3 | transitive | MIT | Installed metadata + 1 bundled license file | [source](https://github.com/crate-py/rpds) |
| typing-extensions | 4.16.0 | transitive | PSF-2.0 | [PyPI metadata](https://pypi.org/pypi/typing-extensions/4.16.0/json); not installed | [source](https://github.com/python/typing_extensions) |
| urllib3 | 2.8.0 | transitive | MIT | Installed metadata + 1 bundled license file | [source](https://github.com/urllib3/urllib3) |

## Advisory check

After updating the pinned `lxml` and `requests` versions, this read-only command exited 0:

```sh
uvx pip-audit --path .venv/lib/python3.13/site-packages --format json --desc off --aliases off --progress-spinner off
```

`pip-audit` 2.10.1, using its PyPI advisory service, reported **no known vulnerabilities** for the 19 installed third-party distributions. It skipped the editable local `anki-pipeline==3.0.0rc1` because that project is not on PyPI. The conditional `typing-extensions==4.16.0` lock entry was not installed; a separate pinned `pip-audit --no-deps` query returned no known vulnerabilities for it. Across these two checks, all 20 locked third-party identities were queried, while the local project was skipped. This is a point-in-time advisory database lookup, not proof that dependencies or application code are free of vulnerabilities.

An earlier audit of the pre-upgrade environment found two unique advisories (the tool listed each twice): [lxml `6.0.0`, PYSEC-2026-87 / CVE-2026-41066](https://github.com/lxml/lxml/security/advisories/GHSA-vfmq-68hx-4jfw), fixed in `6.1.0`, and [requests `2.32.4`, PYSEC-2026-2275 / CVE-2026-25645](https://github.com/psf/requests/security/advisories/GHSA-gc5v-m9x4-r6x2), fixed in `2.33.0`. Those patched versions are now locked and installed. The lxml advisory concerns default `iterparse()` and `ETCompatXMLParser()` handling of untrusted XML; the requests advisory concerns direct calls to `extract_zipped_paths()`. A source search of `anki_pipeline` found neither affected API call, although keeping patched versions is still appropriate.

## License and content boundaries

`PyMuPDF==1.26.3` declares dual licensing: GNU AGPL 3.0 or an Artifex commercial license. Its installed `COPYING` file repeats that declaration, and the [upstream project](https://github.com/pymupdf/PyMuPDF#licensing) describes the two routes. The current CLI runs locally for private personal use; the [GNU FAQ on private running](https://www.gnu.org/licenses/gpl-faq.en.html#NoDistributionRequirements) says copies run without conveyance do not by themselves require public source release. That does not settle whether this particular combined program may be shared under specific terms. Sharing code or binaries with others, or offering a network service, needs a separate license decision before release. A source-only private repository does not itself replace that review, and this document gives no legal guarantee.

Other points to retain for a release review: `frozendict` declares LGPL v3; `certifi` declares MPL-2.0; `lxml` declares BSD-3-Clause but its bundled `LICENSES.txt` lists component exceptions. `cached-property` declares only “BSD” without a precise SPDX variant. `et-xmlfile` and `openpyxl` declare MIT in installed metadata, but no license file was found in their installed distributions. The local `anki-pipeline` project declares no license in `pyproject.toml`; this inventory does not assign one.

The source repository’s `.gitignore` excludes `.venv/`, `data/`, `output/`, and `backups/`; configured legacy database, workbook, and audio are read from the sibling `anki_template` tree. These boundaries are intended to keep third-party exam examples, dictionary content, pronunciation media, and generated `.apkg` files out of a source-only repository. The ignore rules do not prove what a future commit or published archive contains; inspect the release manifest before sharing. No third-party corpora or audio are licensed by this dependency inventory.
