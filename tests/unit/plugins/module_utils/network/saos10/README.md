# Offline tests for the saos10 resource-module pipeline

`test_fps_offline.py` proves, without a device, that the shared resource-module
template turns a `want`/`have` diff into NETCONF XML and hands it to
`edit_config`, then recomputes `changed` from a second fact gather. `fps` is the
canonical list-based module; `mpls` covers the singleton/dict variant and its
root-level `operation="delete"`.

## Run

```bash
pip install -r requirements.txt -r requirements-test.txt
ansible-galaxy collection install ansible.netcommon
# the collection must be importable as ansible_collections.ciena.saos10
mkdir -p ~/.ansible/collections/ansible_collections/ciena
ln -s "$PWD" ~/.ansible/collections/ansible_collections/ciena/saos10
python -m pytest tests/unit -q
```

`pytest-ansible` (in `requirements-test.txt`) puts the collection on the import
path; without it, export `PYTHONPATH=~/.ansible/collections`. Running pytest
may create an untracked `collections/` symlink tree in the repo root; do not
commit it.

## What the tests cover

| Group | Seam | Proves |
|---|---|---|
| Golden XML | `cls.__new__(cls)` + `_module = MagicMock()` | `set_config` -> `_create_xml_config_generic` output for merged (list and dict), deleted, key translation, booleans, `None` leaves, nesting; `mpls` root `operation="delete"` sentinel |
| Mocked round-trip | `patch.object(Fps, "get_facts", side_effect=[before, after])` | `edit_config` called once with `target="running"` and an `<nc:config xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">` wrapper; `changed`/`before`/`after`/`xml` populated; no call when `want == have`; `{"failed": True}` on RPC error |
| Facts fixture | `FpsFacts.populate_facts(..., data=<lxml Element>)` | Fixture XML -> argspec-validated dict, type coercion (`mtu-size` -> `int`), round-trip equality with an argspec-shaped `want` |
| `test_characterize_*` | as above | Pins current behaviour, including suspected bugs (below). A fix must update the test. |

### Behaviour pinned by characterization tests

Verified by reading the repository only; not remediated here.

- `ptps._state_deleted` reads `config["ptp-id"]` while the argspec/facts key is
  `ptp_id` -> `KeyError` on every delete.
- `logical_ports` argspec `state.choices == ["merged"]`, so its `_state_deleted`
  is unreachable (it works when called directly).
- `create_xml_config_from_list` pops `operation` from the caller's dicts; a
  second serialisation of the same list loses the delete attribute. A strict
  `xfail` test asserts the non-mutating behaviour and will start failing
  (XPASS) once fixed.
- `NAMESPACE` for `logical_ports` and `classifiers` contains `::`
  (`ciena-pn::ciena-mef-...`); `fps`/`fds` use a single colon.
- `execute_module`'s `result["changed"] = True` after `edit_config` is dead:
  `config_is_diff(have, changed_facts)` overwrites it. A device that accepts the
  RPC but reports unchanged facts yields `changed=False`.
- The `elif self.state == "gathered"` branch is unreachable from any argspec.
- **Config/facts item-name mismatch (fps):** config emits `<fps><fp>`
  (`XML_ITEMS = "fp"`), but `FpsFacts` matches `//fps/fps`. Fed the config
  side's own output, the parser returns nothing. Which shape the device
  actually returns is unknown offline; `tests/integration/live/README.md` marks
  fps facts "OK" on SAOS 10-11-02, which is consistent with either the device
  returning `<fps><fps>` or the check not inspecting the parsed content.
- `FpsFacts.recursive_config_fill` only walks dict/scalar spec entries, so
  list-of-dict leaves (`normalized_vid`) never appear in facts; `merged` can
  never be idempotent for items that set them.
- `if not data:` in `populate_facts` is falsy for a childless lxml element, so
  an empty `<fps/>` passed via `data=` still triggers a live `get`.

## Backward-compatibility risks

- Tests bind to the `cls.__new__(cls)` + `MagicMock` seam. Moving XML
  generation or facts parsing behind the connection object, or adding required
  state to `ConfigBase.__init__`, breaks them without a source-level signal.
  Acceptable alternative seam: `patch.object(ConfigBase, "__init__")`.
- `list_item.pop("operation")` mutation means tests pass fresh dicts per call
  (as real callers do). Fixing the mutation changes no public behaviour but
  invalidates `test_characterize_create_xml_config_from_list_mutates_caller_items`
  and flips the strict `xfail`.
- Namespace strings are asserted literally. Correcting `::` -> `:` changes the
  emitted XML; the golden tests will flag it (intended), and consumers diffing
  `result["xml"]` will observe the change.
- Pinning the `ptps` `KeyError` codifies a bug; the fix requires updating the
  test.
- `execute_module` re-gathers facts unconditionally. Any stub of `get_facts`
  must supply two return values; a bare `MagicMock` return corrupts
  `config_is_diff` (a `MagicMock` never compares equal to a list).
- Golden facts fixtures use the `<fps><fps>` item shape the parser accepts
  today. If the parser is corrected to `//fps/fp`, those fixtures and the
  item-name characterization test must change together.

## Explicitly unverified claims

Nothing in this directory proves:

- that the `urn:ciena:...` / `http://ciena.com/...` namespaces, the `<fp>` item
  name, or the subtree filters match a live SAOS 10 YANG model (the `::` vs `:`
  inconsistency and the `<fp>`/`<fps>` item-name mismatch are direct evidence of
  drift risk);
- that the device accepts the emitted NETCONF `edit_config` semantics
  (`target="running"`, the `operation="delete"` attribute on list items or on
  the `<mpls>` root, absence of `<nc:config>` locking/commit);
- that `render_config` output matches real device XML for any module other
  than `fps` (only `FpsFacts` and the `mpls` singleton lookup were inspected);
- `supports_check_mode` handling, `ACTION_STATES` membership (inherited from
  the external `ansible.netcommon` `ConfigBase`), or `state` choices for modules
  other than `fps`, `mpls`, `ptps`, `logical_ports`;
- end-to-end idempotency: `changed` is recomputed from a re-gather
  (`config_is_diff(have, changed_facts)`), so it depends on the device
  returning canonical data in the same types and order as the argspec -
  untestable offline;
- whether `tests/integration/live/playbook.yml` asserts on `changed` or parsed
  facts (it runs merge/delete/facts tasks but its assertions were not audited
  here).
