# Dependency and CI supply-chain audit — `ciena.saos10`

| | |
|---|---|
| Audit date | 2026-09-28 (UTC) |
| Repository / ref | `COG-GTM/ciena.saos10`, `master` @ `dc2ac46` |
| Python | 3.12.13 (fresh `venv`) |
| pip | 26.2.1 |
| pip-audit | 2.10.1 (PyPI advisory DB + OSV, queried live on the audit date) |
| SBOMs | `security/sbom.cyclonedx.json` — full development/CI environment (`requirements.txt` + `requirements-test.txt`), CycloneDX 1.4, 54 components. `security/sbom-runtime.cyclonedx.json` — runtime only (`requirements.txt`, what `release.yml` installs), CycloneDX 1.4, 15 components. Both generated with `pip-audit --format cyclonedx-json`. Neither describes the Galaxy artifact itself, which contains no Python distributions — only the collection's own code. |
| Advisory metadata | OSV API (`https://api.osv.dev/v1/vulns/<id>`) for aliases and CVSS vectors; severities below are the CVSS 3.1 base score computed from those vectors |

## 1. Scope and inventory

Files that define the dependency surface, **as found on `master` @ `dc2ac46` before this PR** (the floors changed by this PR are listed in §3):

| File | Content | Notes |
|---|---|---|
| `requirements.txt` | `ansible-core>=2.16`, `paramiko`, `lxml`, `ncclient`, `xmltodict` | Runtime deps used by the collection's `netconf`/`cliconf` plugins (via `ansible.netcommon`). Installed by `release.yml` before `ansible-galaxy collection build`. |
| `requirements-test.txt` | `black>=24.3.0`, `flake8>=7.0.0`, `mock>=5.1.0`, `pexpect>=4.9.0`, `pytest-xdist>=3.5.0`, `pytest-ansible>=24.0.0`, `yamllint>=1.35.0`, `coverage>=7.4.0`, `tox>=4.14.0` (no explicit `pytest` entry) | Development/CI only. None of this is shipped in the Galaxy artifact. |
| `galaxy.yml` | `dependencies: ansible.netcommon: ">=6.0.0"` | Only collection dependency. Current Galaxy release is 8.7.1 (pulls `ansible.utils` 6.1.1). |
| `tox.ini` | `linters` env = `black -l79 --check`, `flake8`, `yamllint -s .`; deps from both requirement files | No version pins beyond the requirement files. |
| `.pre-commit-config.yaml` | `pre-commit-hooks v4.6.0`, `black 24.4.2`, `yamllint v1.35.1`, `ansible-lint v24.5.0` | All four `rev:` values are immutable tags — nothing floats. |
| `.github/workflows/ansible-test.yml` | `uses: ansible-network/github_actions/.github/workflows/{ansible-lint,sanity}.yml@main` | **Unpinned branch reference** (see §4). |
| `.github/workflows/extra-docs-linting.yml` | `actions/checkout@v4`, `actions/setup-python@v5`, `pip install antsibull-docs` | Tag-pinned actions (mutable tags), unpinned pip install. |
| `.github/workflows/release.yml` | `actions/checkout@v4`, `actions/setup-python@v5`, `pip install -r requirements.txt`, `ansible-galaxy collection publish --api-key ${{ secrets.GALAXY_API_KEY }}` | Runs on **every push to `master`/`main`**; publishes with a long-lived Galaxy token. |

Every requirement is a *floor* (`>=`) or completely unpinned, so what actually gets installed depends on the day the install runs. The audit therefore looks at two things: (a) what a fresh resolution installs today, and (b) whether the *declared minimums* admit versions with known vulnerabilities.

## 2. Python dependency findings

### 2.1 Resolved environment (what `pip install -r requirements.txt -r requirements-test.txt` gives today)

```
$ pip-audit                                    # against the installed venv
No known vulnerabilities found
$ pip-audit -r requirements.txt -r requirements-test.txt
No known vulnerabilities found
```

Resolved versions of interest: `ansible-core 2.21.4`, `paramiko 5.0.0`, `cryptography 50.0.1`, `lxml 6.1.3`, `ncclient 0.7.1`, `xmltodict 1.0.4`, `Jinja2 3.1.6`, `PyYAML 6.0.3`, `black 26.5.1`, `pytest 9.1.1`, `pytest-ansible 26.9.0`, `yamllint 1.38.0`, `tox 4.64.4`. Full list: the SBOM.

**Result: 0 findings before and after this change.** The fresh resolution was already clean; the problem is in the floors.

### 2.2 Declared floors (what the requirement files *allow* to be installed)

Auditing each declared minimum as if it were pinned (`pip-audit -r floors.txt --no-deps`):

```
Found 17 known vulnerabilities in 3 packages      # 9 unique advisories after de-duplication
```

| Package | Floor (before) | Advisory | CVE / GHSA | Severity (CVSS 3.1) | Fixed in (2.16 branch / minimum) | Reachable from this collection? |
|---|---|---|---|---|---|---|
| ansible-core | 2.16.0 | PYSEC-2024-36 | CVE-2024-0690 / GHSA-h24r-m9qc-pvpg | 5.5 Medium | 2.16.3 | **Partially.** `ANSIBLE_NO_LOG` ignored for loop items. Users who loop `saos10_command`/config modules over items containing credentials with `no_log: true` could leak them in output. Controller-side. |
| ansible-core | 2.16.0 | PYSEC-2026-1122 | CVE-2023-5764 / GHSA-7j69-qfc3-2fq9 | 7.1 High | 2.16.1 | **Yes (controller).** Templating can drop the `unsafe` marker. Device output returned by `saos10_facts`/`saos10_command` is untrusted data that playbooks routinely template. |
| ansible-core | 2.16.0 | PYSEC-2026-1121 | CVE-2024-9902 / GHSA-32p4-gm2c-wmch | 6.3 Medium | 2.16.13 | **No.** Only affects the `user` module against a local/remote Linux host. This collection never runs `user`; SAOS 10 targets are network devices reached over `network_cli`/`netconf`. |
| ansible-core | 2.16.0 | PYSEC-2026-1124 | CVE-2024-8775 / GHSA-jpxc-vmjf-9fcj | 5.5 Medium | 2.16.13 | **Indirectly.** Vaulted vars loaded via `include_vars` without `no_log` are printed. Not in collection code; affects playbooks that store device credentials in Vault. |
| ansible-core | 2.16.0 | PYSEC-2026-1123 | CVE-2024-11079 / GHSA-99w6-3xph-cx78 | 5.5 Medium | 2.16.14 | **Yes (controller).** `hostvars` unsafe-bypass → template execution from remote data. Facts gathered from a device (`saos10_facts`) land in `hostvars`; a compromised or hostile device could supply crafted strings. |
| ansible-core | 2.16.0 | PYSEC-2026-3458 | CVE-2026-11332 / GHSA-w8p5-mx5w-cpqj | 7.8 High | 2.16.19 | **No.** `ansible-galaxy role install` git-flag injection via `meta/requirements.yml`. This collection ships no roles and its CI only *builds/publishes* the collection; it does not install roles. |
| black | 24.3.0 | PYSEC-2026-2121 | CVE-2026-32274 / GHSA-3936-cmfr-pm3m | 7.5 High | 26.3.1 | **No.** Arbitrary cache-file write via `--python-cell-magics`. Neither `tox.ini` nor `.pre-commit-config.yaml` pass that option; dev-only tool, not shipped. |
| black | 24.3.0 | PYSEC-2026-2120 | CVE-2026-31900 / GHSA-v53h-f6m7-xcgm | 9.8 Critical | 26.3.0 | **No.** Affects the `psf/black` *GitHub Action* with `use_pyproject: true`. This repo does not use the action (black runs via tox/pre-commit) and has no `pyproject.toml`. |
| pytest (transitive via pytest-xdist / pytest-ansible) | 7.4.4 (forced by `pytest-ansible 24.1.0`'s `pytest<8` cap) | PYSEC-2026-1845 | CVE-2025-71176 / GHSA-6w46-j5rx-g56g | 6.8 Medium | 9.0.3 | **No (dev only).** Predictable `/tmp/pytest-of-<user>` directory on shared UNIX hosts. Only relevant when running the unit tests on a multi-user machine; CI runners are single-tenant. |

Counts by severity at the declared floors, **before**: 1 Critical, 3 High, 5 Medium, 0 Low (9 unique advisories, 3 packages).
**After** raising the floors (§3): `pip-audit -r floors-after.txt --no-deps` → `No known vulnerabilities found` (0 / 0 / 0 / 0).

Also found while auditing the floors: `pytest-ansible>=24.0.0` refers to a release that does not exist (the 24.x line starts at 24.1.0), so pip silently resolves past it; the floor was giving no guarantee at all.

### 2.3 Runtime libraries with no version floor

`paramiko`, `lxml`, `ncclient`, `xmltodict` are completely unpinned. Today's resolution (`paramiko 5.0.0`, `lxml 6.1.3`, `ncclient 0.7.1`, `xmltodict 1.0.4`) is clean. No floor was added for these in this PR because the collection does not import them directly — they are consumed through `ansible.netcommon`'s `netconf`/`network_cli` connection plugins, whose own floors govern compatibility. Recommendation (not applied): add floors that match the oldest versions `ansible.netcommon>=6.0.0` supports, or better, adopt a `constraints.txt` for CI (see §5).

## 3. Remediation applied in this PR

| File | Change | Why it is safe |
|---|---|---|
| `requirements.txt` | `ansible-core>=2.16` → `ansible-core>=2.16.19` | 2.16.19 is the final 2.16.x release (2026-06-18) and contains the fixes for all six ansible-core advisories above. It stays inside the `>=2.16` support statement, and nothing in the collection uses APIs removed between 2.16.0 and 2.16.19. The fresh resolution (2.21.4) is unchanged — `pip freeze` before/after is identical. |
| `requirements-test.txt` | `black>=24.3.0` → `black>=26.3.1` | Dev-only. The `tox -e linters` env already resolves to the latest black (26.5.1) because the requirement is a floor, so this changes nothing about what CI runs; it only stops a stale local venv from satisfying the requirement with a vulnerable release. |
| `requirements-test.txt` | add `pytest>=9.0.3` | Dev-only. Current resolution already installs pytest 9.1.1; `pytest-xdist>=3.5.0` requires only `pytest>=6.2.0`. |
| `requirements-test.txt` | `pytest-ansible>=24.0.0` → `pytest-ansible>=24.8.0` | 24.0.0 never existed. 24.8.0 is the first release whose metadata is `pytest>=6` (24.1.0 caps `pytest<8`, which would conflict with the new pytest floor). Current resolution (26.9.0) unchanged. |
| `tests/integration/live/playbook.yml` | re-indent one comment | Makes `yamllint -s .` (part of `tox -e linters`) pass; no YAML semantics changed. |
| `changelogs/fragments/supply-chain.yml` | `security_fixes` + `trivial` fragment | antsibull-changelog format used by this repo. |
| `security/DEPENDENCY-AUDIT.md`, `security/sbom.cyclonedx.json`, `security/sbom-runtime.cyclonedx.json` | this report and the SBOMs | Documentation only. |

`.pre-commit-config.yaml` was **not** changed: every `rev:` is already an immutable tag. Bumping `psf/black` there to 26.x was evaluated and rejected — black 26 at `--line-length=160` would reformat 70 files (10 with the current 24.4.2), which is out of scope and would collide with in-flight work. The two black advisories are not reachable through the pre-commit hook (§2.2).

## 4. CI supply chain

### 4.1 Unpinned reusable workflows (`.github/workflows/ansible-test.yml`)

```yaml
  ansible-lint:
    uses: ansible-network/github_actions/.github/workflows/ansible-lint.yml@main
  sanity:
    uses: ansible-network/github_actions/.github/workflows/sanity.yml@main
```

`@main` is a moving branch. Anyone who can push to `ansible-network/github_actions` (or who compromises that repo) can change what runs inside this repo's CI on the next PR, with this repo's `GITHUB_TOKEN`. The reusable workflows themselves check out this collection and run `ansible-lint` / `ansible-test sanity`, i.e. they execute arbitrary code from that upstream repo.

Workflow files are out of scope for this PR (concurrent work), so the exact replacement is recorded here. `refs/heads/main` of `ansible-network/github_actions` resolved to `4678c74a7d712d55e663c88f66eec6d9c3642550` on 2026-09-28:

```yaml
  ansible-lint:
    uses: ansible-network/github_actions/.github/workflows/ansible-lint.yml@4678c74a7d712d55e663c88f66eec6d9c3642550  # main @ 2026-09-28
  sanity:
    uses: ansible-network/github_actions/.github/workflows/sanity.yml@4678c74a7d712d55e663c88f66eec6d9c3642550  # main @ 2026-09-28
```

Caveats: the upstream repository publishes no release tags, so a SHA pin is the only immutable option, and it must be refreshed deliberately (Dependabot `github-actions` ecosystem handles SHA-pinned `uses:` and will open bump PRs). The reusable workflows internally reference other actions by tag; pinning the caller SHA fixes *which* version of those references is used, but not their own mutability.

### 4.2 Tag-pinned third-party actions

`actions/checkout@v4` and `actions/setup-python@v5` (both in `extra-docs-linting.yml` and `release.yml`) use mutable major-version tags. SHA-pinned equivalents as of 2026-09-28:

```yaml
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4.4.0
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065  # v5.6.0
```

### 4.3 Release pipeline (`release.yml`)

* Publishes to Ansible Galaxy on **every push to `master`/`main`**, not on a tag or release. Any merged PR that changes `galaxy.yml`'s `version` (or any push, if Galaxy accepts re-publishing) reaches users immediately. Recommendation: trigger on `release: [published]` or `push: tags: ['v*']`, and add `environment: release` with required reviewers so the `GALAXY_API_KEY` secret is only exposed to an approved job.
* `pip install -r requirements.txt` inside the release job is unpinned — the build environment is whatever PyPI serves that day. Recommendation: install from a hash-pinned `constraints.txt` (`pip-compile --generate-hashes`) in the release job.
* `ls *.tar.gz | xargs ansible-galaxy collection publish` — fine as long as only one artifact is built; `ansible-galaxy collection build --output-path dist/` plus an explicit path would be more robust.
* No job-level `permissions:` block — the default `GITHUB_TOKEN` scope applies. Add `permissions: contents: read` (the docs-lint workflow already does this).

### 4.4 Pre-commit hooks

All revs are immutable tags (`v4.6.0`, `24.4.2`, `v1.35.1`, `v24.5.0`); no floating refs. They lag the current tags (`v6.0.0`, `26.5.1`, `v1.38.0`, `v26.9.0`) but carry no advisory that is reachable from how the hooks are invoked here. Note the two inconsistencies that already exist on `master`: pre-commit runs black at `--line-length=160` while `tox -e linters` runs it at `-l79`, and the pinned hook (24.4.2) differs from the tox-resolved black (26.x), so the two entry points disagree on formatting.

## 5. Not fixed (and why)

| Item | Reason |
|---|---|
| `@main` reusable workflows, tag-pinned actions, release trigger | `.github/workflows/` is out of scope for this PR (concurrent work). Exact replacement lines are in §4. |
| Floors for `paramiko`/`lxml`/`ncclient`/`xmltodict` | Not imported by collection code; governed by `ansible.netcommon`. Adding arbitrary floors gives no security benefit today (0 findings) and risks conflicting with netcommon's own constraints. |
| Hash-pinned lockfile / `constraints.txt` | Recommended but a workflow/process change: the release job would need to consume it. Left for a follow-up. |
| `.pre-commit-config.yaml` black bump | Would reformat 70 files; advisories not reachable. |
| Pre-existing `tox -e linters` failures | `black -l79 --check` reports 96 files "would reformat" and `flake8` reports 9 `F401 're' imported but unused` in `plugins/module_utils/network/saos10/facts/*/*.py` on unmodified `master`. Verified identical before and after this change with black 26.5.1 **and** black 24.4.2 (so not caused by the black floor bump). Fixing them means touching plugin code that is out of scope. `yamllint -s .` (the third linters step) is now clean. |

## 6. Verification log

Commands run in the fresh venv (`~/venv-saos`, Python 3.12.13) at the repository root; `ansible.netcommon 8.7.1` installed with `ansible-galaxy collection install ansible.netcommon` because the unit tests import it.

| Step | Before (master `dc2ac46`) | After (this branch) |
|---|---|---|
| `pip-audit` (installed env) | No known vulnerabilities found | No known vulnerabilities found |
| `pip-audit -r requirements.txt -r requirements-test.txt` | No known vulnerabilities found | No known vulnerabilities found |
| `pip-audit -r <declared floors> --no-deps` | 17 rows / 9 unique advisories / 3 packages | No known vulnerabilities found |
| `pip freeze` | 54 distributions | identical (`diff` empty) |
| `pytest tests/unit -q` | 27 passed | 27 passed |
| `yamllint -s .` | 1 warning (`tests/integration/live/playbook.yml:38 comments-indentation`), exit 2 | clean, exit 0 |
| `flake8` | 9 × F401 (pre-existing) | 9 × F401 (unchanged, out of scope) |
| `black -l79 --check .` | 96 files would be reformatted (pre-existing; same with black 24.4.2) | unchanged |
| `tox -e linters` | FAIL (black step) | FAIL (black step, identical) |
| `pip-audit -r requirements.txt -r requirements-test.txt --format cyclonedx-json` | — | `security/sbom.cyclonedx.json`, CycloneDX 1.4, 54 components (dev/CI environment) |
| `pip-audit -r requirements.txt --format cyclonedx-json` | — | `security/sbom-runtime.cyclonedx.json`, CycloneDX 1.4, 15 components (release-job environment) |

## 7. Suggested follow-ups (not in this PR)

1. Apply the SHA pins from §4.1/§4.2 and add Dependabot (`github-actions` + `pip` ecosystems) to keep them fresh.
2. Move the Galaxy publish to a tag/release trigger behind a protected `environment`.
3. Add a `constraints.txt` generated with `pip-compile --generate-hashes` and use it in `tox.ini` and `release.yml`.
4. Add a scheduled `pip-audit` job (or enable GitHub Dependency Review / Dependabot alerts on the fork) so the floors audit in §2.2 is re-run automatically.
5. Fix the pre-existing `tox -e linters` failures (black `-l79` vs `--line-length=160` disagreement, unused `re` imports) once the concurrent plugin changes land.
