# Unit tests

The unit tests run entirely offline: no SAOS 10 device, credentials or
network access are needed.

## Layout

| Path | Purpose |
| --- | --- |
| `plugins/modules/saos10_module.py` | Shared harness for the NETCONF resource modules. It stubs the NETCONF `get` used by the facts classes with fixture XML and replaces the resource connection with a `MagicMock` so every `edit_config` call is captured. |
| `plugins/modules/test_saos10_{fps,fds,classifiers}.py` | One test class per resource module covering `merged`, `deleted`, `gathered`, `rendered`, `parsed`, check mode, idempotence and argument validation. |
| `plugins/modules/fixtures/` | `<resource>_running.xml` / `<resource>_empty.xml` are `<get>` replies; `<resource>_merged.xml` / `<resource>_deleted.xml` are the golden payloads expected inside `<nc:config>` for `edit_config`. |
| `plugins/modules/test_saos10_command.py`, `plugins/cliconf/`, `plugins/module_utils/` | Pre-existing tests for the CLI side of the collection. |

## Running

The collection has to be importable as `ansible_collections.ciena.saos10`,
so clone (or symlink) it into `<root>/ansible_collections/ciena/saos10` and
install the dependencies:

```bash
pip install "ansible-core>=2.16" -r requirements.txt -r requirements-test.txt
ansible-galaxy collection install ansible.netcommon ansible.utils
```

Then, from the collection root:

```bash
ansible-test units --python 3.12          # or --docker default
# or
pytest tests/unit -q
```

`pytest` can also be pointed at a single file or test:

```bash
pytest tests/unit/plugins/modules/test_saos10_fps.py -q
pytest tests/unit -q -k "rendered or parsed"
```

## Adding a resource module

1. Capture a `<get>` reply for the resource and save it as
   `fixtures/<resource>_running.xml`; add an empty
   `<data xmlns="urn:ietf:params:xml:ns:netconf:base:1.0"/>` as
   `fixtures/<resource>_empty.xml`.
2. Run the module once against the harness, copy the captured `edit_config`
   payload (minus the `<nc:config>` wrapper) into
   `fixtures/<resource>_merged.xml` / `<resource>_deleted.xml`.
3. Subclass `TestSaos10Module`, set `module` and `resource`, and mirror the
   tests in `test_saos10_fps.py`.
