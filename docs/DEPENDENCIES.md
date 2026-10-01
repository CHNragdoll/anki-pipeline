> 历史基线：本页记录 rc.1 阶段的范围与结果。rc.2 的当前检查、限制和发布条件见 [RELEASE_RC2.md](RELEASE_RC2.md)。

# Dependency and license inventory

> 2026-10-01 更新：本项目原创源码已按用户要求采用 [MIT](../LICENSE)，并在 `pyproject.toml` 声明。下文 rc.1 盘点中“项目未声明许可”的文字保留为历史事实；它不再描述当前源码。第三方依赖、词典、真题、音频和词源资源的许可保持原状，MIT 不赋予这些资料新的传播权利。当前版本新增的 Node 测试依赖在 `package-lock.json` 单独锁定，不属于下文的旧 Python 依赖盘点。

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

## Verified license details

The installed `PyMuPDF==1.26.3` metadata and `COPYING` marker both say “GNU AFFERO GPL 3.0 or Artifex Commercial License”; the [exact PyPI release](https://pypi.org/project/PyMuPDF/1.26.3/) and [upstream licensing page](https://github.com/pymupdf/PyMuPDF#licensing) confirm those alternatives. The installed `COPYING` marker is a one-line declaration, not a complete copy of the AGPL terms. No Artifex commercial license was supplied or assumed.

The installed `requests==2.33.0` wheel contains Apache-2.0 `LICENSE` and a separate `NOTICE` naming Requests and Kenneth Reitz. `frozendict` includes LGPL version 3 text; `certifi` includes MPL-2.0 text. `lxml` includes BSD-3-Clause text and `LICENSES.txt`, which describes component and resource exceptions. `cached-property` metadata says only “BSD”, while its installed license text has three redistribution/non-endorsement conditions; this inventory retains the upstream metadata wording rather than assigning an unverified SPDX identifier.

The installed `openpyxl==3.1.5` and `et-xmlfile==2.0.0` distributions did not contain separate license files. I checked their **exact locked source archives** against the SHA-256 hashes in `uv.lock`: [openpyxl 3.1.5](https://pypi.org/project/openpyxl/3.1.5/) contains `LICENCE.rst` (MIT text, SHA-256 `0c84bb42f5d367e5ebf9fc2dde35b16141df5ee0fdc189250858bc6c5560f69e`); [et-xmlfile 2.0.0](https://pypi.org/project/et-xmlfile/2.0.0/) contains the same `LICENCE.rst` plus `LICENCE.python`, which points to it. This resolves the missing installed-file evidence for those two releases without copying their files into this source repository. The local `anki-pipeline` project still has no declared license in `pyproject.toml`; this record does not invent one.

## SUP-004 decision for this candidate

| Topic | Recorded current scope and decision |
| --- | --- |
| Intended use | Owner-only, local CLI trial and private source-only backup. Run pinned, unmodified third-party packages from the local environment. This is the current scope decision; it is not an assertion that every future use is licensed. |
| Modification | The project source is being changed. No third-party dependency source or wheel is modified or vendored in this repository. If that changes, inspect the affected package terms and notices again. |
| Distribution | No public repository, collaborator sharing, package/binary redistribution, hosted service, or third-party content distribution is in this candidate scope. A private owner backup is not being treated as a request for a public-distribution license decision. |
| Disclosure and attribution | License identities, upstream sources, and installed license-file hashes are recorded in [dependencies.json](dependencies.json). Installed package notices remain in `.venv`; the repository does not bundle those packages. If a later scope conveys dependencies, prepare the applicable license texts and notices, including Requests `NOTICE`, rather than assuming this inventory alone is sufficient. |
| Commercial constraints | No commercial product or Artifex commercial authorization is claimed. PyMuPDF's AGPL/commercial choice must be assessed against a concrete changed use, such as distributing a combined application or operating a service for others. |

For private copies and running without conveyance, the [GNU license FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#NoDistributionRequirements) describes no public source-release requirement. That general explanation does not decide whether any particular private hosting arrangement or combined work is legally “conveyed,” and the AGPL has additional network-use provisions. This document records the operating boundary, not a legal compliance guarantee or approval to publish.

The repository’s `.gitignore` excludes `.venv/`, `data/`, `output/`, and `backups/`; configured legacy database, workbook, and audio are in the sibling `anki_template` tree. The intended source-only candidate excludes original exam/dictionary corpora, pronunciation media, generated `.apkg` files, and installed dependency binaries. These materials have no redistribution authorization recorded here. Ignore rules alone do not verify the actual commit or archive manifest, so that remains a separate factual check before any change in sharing scope.

Remaining evidence gaps are limited but real: no license declaration has been selected for the owner's own project; no commercial PyMuPDF license or rights to redistribute third-party corpora/media have been shown; the actual private-repository access list and final file manifest were outside this documentation check. None of those gaps is treated here as permission to expand distribution, nor as a reason to stop the already scoped private backup. Reassess if access, use, modified dependencies, or deliverables change.
