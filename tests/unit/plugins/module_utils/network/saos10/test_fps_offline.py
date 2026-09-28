# Copyright 2026 Ciena Corp
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Device-free proof that the saos10 resource-module pipeline
``want/have diff -> XML -> edit_config -> re-gather -> changed`` works.

Nine resource modules share one template (``config/{bgp,classifiers,fds,fps,
isis,ldp,logical_ports,mpls,ptps}``). ``fps`` is used as the canonical
list-based module (single-colon namespace, ``<fps><fp>`` items). ``mpls`` is
covered minimally as the singleton/dict variant whose delete path emits an
``operation="delete"`` attribute on the *root* element via the
``_ROOT_OPERATION_KEY`` sentinel.

Seams used (no device, no ncclient socket):

* ``cls.__new__(cls)`` + ``instance._module = MagicMock()`` skips
  ``ConfigBase.__init__`` (which would call ``get_resource_connection``).
  Same seam as ``tests/unit/plugins/module_utils/test_config_bool_serialization.py``.
* ``unittest.mock.patch.object(Fps, "get_facts", side_effect=[before, after])``
  replaces the two unconditional fact gathers in ``execute_module``.
* ``FpsFacts.populate_facts(..., data=<lxml Element>)`` bypasses the NETCONF
  ``get`` and parses a fixture directly.

Tests whose name starts with ``test_characterize_`` pin *current* behaviour,
including behaviour that looks like a bug. They are meant to fail loudly when
the underlying code is fixed so the fix is a deliberate, reviewed change.
Nothing in this file proves the emitted XML is accepted by a real SAOS 10
device; see README.md in this directory for the list of unverified claims.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import copy

from unittest.mock import MagicMock, patch

import pytest

from lxml.etree import fromstring

from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.argspec.logical_ports.logical_ports import LogicalPortsArgs
from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.argspec.ptps.ptps import PtpsArgs
from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.config.classifiers import classifiers as classifiers_config
from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.config.fds import fds as fds_config
from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.config.fps import fps as fps_config
from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.config.fps.fps import Fps
from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.config.logical_ports import logical_ports as logical_ports_config
from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.config.logical_ports.logical_ports import LogicalPorts
from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.config.mpls.mpls import Mpls
from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.config.ptps.ptps import Ptps
from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.facts.fps import fps as fps_facts_module
from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.facts.fps.fps import FpsFacts
from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.utils.utils import config_is_diff

FPS_NS = "urn:ciena:params:xml:ns:yang:ciena-pn:ciena-mef-fp"
MPLS_NS = "http://ciena.com/ns/yang/ciena-mpls"
NC_CONFIG_OPEN = '<nc:config xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">'
NC_CONFIG_CLOSE = "</nc:config>"


def make_config_instance(cls, config, state):
    """Build a resource-module config object without touching ConfigBase.__init__."""
    instance = cls.__new__(cls)
    instance._module = MagicMock()
    instance._module.params = {"config": config, "state": state}
    instance.state = state
    return instance


def run_pipeline(cls, want, have, state):
    """set_config -> _create_xml_config_generic, exactly as execute_module does."""
    instance = make_config_instance(cls, want, state)
    config = instance.set_config(have)
    snapshot = copy.deepcopy(config)
    xml = instance._create_xml_config_generic(config) if config else None
    # ``config`` is returned as it was *before* serialisation: the list
    # serialiser pops ``operation`` from the items (see the mutation tests).
    return snapshot, xml


# ---------------------------------------------------------------------------
# a. Golden XML (pure; no connection, no facts)
# ---------------------------------------------------------------------------


def test_fps_merged_list_insert_emits_fps_root_with_fp_items():
    want = [{"name": "fp1", "fd_name": "fd1", "logical_port": "1"}]
    config, xml = run_pipeline(Fps, want, have=[], state="merged")
    assert config == want
    assert xml == f'<fps xmlns="{FPS_NS}"><fp><name>fp1</name><fd-name>fd1</fd-name><logical-port>1</logical-port></fp></fps>'


def test_fps_merged_list_only_emits_items_absent_from_have():
    """Item-level equality: an identical item is skipped, a new or modified one is re-sent whole."""
    existing = {"name": "fp1", "logical_port": "1"}
    modified = {"name": "fp2", "logical_port": "2", "mtu_size": 9000}
    want = [dict(existing), modified, {"name": "fp3", "logical_port": "3"}]
    have = [dict(existing), {"name": "fp2", "logical_port": "2", "mtu_size": 1500}]
    config, xml = run_pipeline(Fps, want, have, state="merged")
    assert config == [modified, {"name": "fp3", "logical_port": "3"}]
    assert xml == (
        f'<fps xmlns="{FPS_NS}">'
        "<fp><name>fp2</name><logical-port>2</logical-port><mtu-size>9000</mtu-size></fp>"
        "<fp><name>fp3</name><logical-port>3</logical-port></fp>"
        "</fps>"
    )


def test_fps_merged_when_want_equals_have_produces_no_config():
    have = [{"name": "fp1", "logical_port": "1"}]
    config, xml = run_pipeline(Fps, copy.deepcopy(have), have, state="merged")
    assert config == []
    assert xml is None


def test_fps_dict_path_wraps_in_namespaced_root():
    """``_create_xml_config_generic`` dispatches a dict to ``create_xml_config_from_dict``."""
    instance = make_config_instance(Fps, {}, "merged")
    xml = instance._create_xml_config_generic({"name": "fp1", "logical_port": "1"})
    assert xml == f'<fps xmlns="{FPS_NS}"><name>fp1</name><logical-port>1</logical-port></fps>'


def test_fps_generic_rejects_non_container():
    instance = make_config_instance(Fps, {}, "merged")
    with pytest.raises(TypeError):
        instance._create_xml_config_generic("not-a-container")
    with pytest.raises(ValueError):
        instance.create_xml_config_from_list(["not-a-dict"])


def test_fps_deleted_emits_operation_delete_on_each_fp():
    want = [{"name": "fp1"}, {"name": "fp2", "logical_port": "ignored-on-delete"}]
    have = [{"name": "fp1", "logical_port": "1"}, {"name": "fp2", "logical_port": "2"}]
    config, xml = run_pipeline(Fps, want, have, state="deleted")
    assert config == [{"name": "fp1", "operation": "delete"}, {"name": "fp2", "operation": "delete"}]
    assert xml == f'<fps xmlns="{FPS_NS}"><fp operation="delete"><name>fp1</name></fp><fp operation="delete"><name>fp2</name></fp></fps>'


def test_fps_deleted_with_empty_want_deletes_everything_in_have():
    have = [{"name": "fp1", "logical_port": "1"}, {"name": "fp2", "logical_port": "2"}]
    config, xml = run_pipeline(Fps, [], have, state="deleted")
    assert [c["name"] for c in config] == ["fp1", "fp2"]
    assert xml.count('operation="delete"') == 2


def test_fps_key_translation_booleans_none_and_nesting():
    """underscore->hyphen keys, YANG-lowercase booleans, None leaves dropped, dict/list nesting."""
    instance = make_config_instance(Fps, {}, "merged")
    xml = instance.create_xml_config_from_list(
        [
            {
                "name": "fp1",
                "mac_learning": "enabled",
                "flag_true": True,
                "flag_false": False,
                "skipped": None,
                "count": 0,
                "normalized_vid": [{"tag": 1, "vlan_id": 100}, {"tag": 2, "vlan_id": 200}],
                "nested_dict": {"inner_key": "v"},
            }
        ]
    )
    assert xml == (
        f'<fps xmlns="{FPS_NS}"><fp>'
        "<name>fp1</name>"
        "<mac-learning>enabled</mac-learning>"
        "<flag-true>true</flag-true>"
        "<flag-false>false</flag-false>"
        "<count>0</count>"
        "<normalized-vid><tag>1</tag><vlan-id>100</vlan-id></normalized-vid>"
        "<normalized-vid><tag>2</tag><vlan-id>200</vlan-id></normalized-vid>"
        "<nested-dict><inner-key>v</inner-key></nested-dict>"
        "</fp></fps>"
    )
    assert "True" not in xml and "False" not in xml and "skipped" not in xml


def test_mpls_merged_dict_emits_singleton_root():
    want = {"interfaces": {"interface": [{"name": "1", "label_switching": True}]}, "label_management": None}
    config, xml = run_pipeline(Mpls, want, have={}, state="merged")
    assert config == {"interfaces": {"interface": [{"name": "1", "label_switching": True}]}}
    assert xml == f'<mpls xmlns="{MPLS_NS}"><interfaces><interface><name>1</name><label-switching>true</label-switching></interface></interfaces></mpls>'


def test_mpls_merged_dict_skips_top_level_keys_already_equal_in_have():
    same = {"interface": [{"name": "1", "label_switching": True}]}
    want = {"interfaces": copy.deepcopy(same), "tunnel_statistics": {"entry": [{"fec_address": "10.0.0.1/32", "owner": "ldp", "role": "ingress"}]}}
    have = {"interfaces": copy.deepcopy(same), "label_management": None, "tunnel_statistics": None}
    config, xml = run_pipeline(Mpls, want, have, state="merged")
    assert list(config) == ["tunnel_statistics"]
    assert xml.startswith(f'<mpls xmlns="{MPLS_NS}"><tunnel-statistics><entry>')


def test_mpls_deleted_emits_operation_delete_on_root():
    config, xml = run_pipeline(Mpls, {}, have={"interfaces": None}, state="deleted")
    assert config == {"_operation": "delete"}
    assert xml == f'<mpls xmlns="{MPLS_NS}" operation="delete"/>'


def test_mpls_deleted_with_nothing_configured_is_a_noop():
    config, xml = run_pipeline(Mpls, {}, have=[], state="deleted")
    assert config == {}
    assert xml is None


def test_mpls_dict_serialiser_does_not_mutate_caller():
    instance = make_config_instance(Mpls, {}, "deleted")
    payload = {"_operation": "delete", "interfaces": {"interface": [{"name": "1"}]}}
    snapshot = copy.deepcopy(payload)
    first = instance.create_xml_config_from_dict(payload)
    second = instance.create_xml_config_from_dict(payload)
    assert payload == snapshot
    assert first == second
    assert 'operation="delete"' in second


# ---------------------------------------------------------------------------
# b. Mocked NETCONF round-trip through execute_module
# ---------------------------------------------------------------------------

BEFORE = [{"name": "fp1", "logical_port": "1"}]
WANT = [{"name": "fp1", "logical_port": "1"}, {"name": "fp2", "logical_port": "2", "mtu_size": 1500}]
AFTER = [{"name": "fp1", "logical_port": "1"}, {"name": "fp2", "logical_port": "2", "mtu_size": 1500}]


def test_execute_module_merged_round_trip():
    instance = make_config_instance(Fps, copy.deepcopy(WANT), "merged")
    edit_config = instance._module._connection.edit_config

    with patch.object(Fps, "get_facts", side_effect=[copy.deepcopy(BEFORE), copy.deepcopy(AFTER)]) as get_facts:
        result = instance.execute_module()

    assert get_facts.call_count == 2
    edit_config.assert_called_once()
    assert edit_config.call_args.kwargs["target"] == "running"
    payload = edit_config.call_args.kwargs["config"]
    expected_xml = f'<fps xmlns="{FPS_NS}"><fp><name>fp2</name><logical-port>2</logical-port><mtu-size>1500</mtu-size></fp></fps>'
    assert payload == NC_CONFIG_OPEN + expected_xml + NC_CONFIG_CLOSE
    # The payload is well-formed XML and the nc: prefix resolves to the base:1.0 namespace.
    root = fromstring(payload.encode())
    assert root.tag == "{urn:ietf:params:xml:ns:netconf:base:1.0}config"
    assert root[0].tag == f"{{{FPS_NS}}}fps"

    assert result == {"changed": True, "xml": expected_xml, "before": BEFORE, "after": AFTER}


def test_execute_module_deleted_round_trip():
    instance = make_config_instance(Fps, [{"name": "fp1"}], "deleted")
    edit_config = instance._module._connection.edit_config

    with patch.object(Fps, "get_facts", side_effect=[copy.deepcopy(BEFORE), []]):
        result = instance.execute_module()

    payload = edit_config.call_args.kwargs["config"]
    assert payload == NC_CONFIG_OPEN + f'<fps xmlns="{FPS_NS}"><fp operation="delete"><name>fp1</name></fp></fps>' + NC_CONFIG_CLOSE
    assert result["changed"] is True
    assert result["before"] == BEFORE
    assert result["after"] == []


def test_execute_module_no_diff_skips_edit_config():
    instance = make_config_instance(Fps, copy.deepcopy(BEFORE), "merged")
    edit_config = instance._module._connection.edit_config

    with patch.object(Fps, "get_facts", side_effect=[copy.deepcopy(BEFORE), copy.deepcopy(BEFORE)]) as get_facts:
        result = instance.execute_module()

    edit_config.assert_not_called()
    assert get_facts.call_count == 2, "facts are re-gathered even when nothing was sent"
    assert result == {"changed": False, "before": BEFORE}
    assert "xml" not in result and "after" not in result


def test_execute_module_edit_config_failure_short_circuits():
    instance = make_config_instance(Fps, copy.deepcopy(WANT), "merged")
    instance._module._connection.edit_config.side_effect = RuntimeError("rpc-error: access-denied")

    with patch.object(Fps, "get_facts", side_effect=[copy.deepcopy(BEFORE), copy.deepcopy(BEFORE)]) as get_facts:
        result = instance.execute_module()

    assert result == {"failed": True, "msg": "rpc-error: access-denied"}
    assert get_facts.call_count == 1, "no re-gather after a failed edit_config"


def test_characterize_changed_is_driven_by_regather_not_by_edit_config():
    """``result["changed"] = True`` after edit_config is dead: the re-gather diff
    overwrites it. If the device accepts the edit but reports unchanged facts,
    the module reports changed=False even though an RPC was sent."""
    instance = make_config_instance(Fps, copy.deepcopy(WANT), "merged")
    edit_config = instance._module._connection.edit_config

    with patch.object(Fps, "get_facts", side_effect=[copy.deepcopy(BEFORE), copy.deepcopy(BEFORE)]):
        result = instance.execute_module()

    edit_config.assert_called_once()
    assert result["changed"] is False
    assert "xml" in result, "the xml that was sent is still reported"
    assert "after" not in result


def test_characterize_gathered_branch_is_unreachable_from_argspec():
    """``execute_module`` has an ``elif self.state == "gathered"`` branch, but no
    argspec in the collection offers ``gathered`` as a state choice."""
    from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.argspec.fps.fps import FpsArgs
    from ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.argspec.mpls.mpls import MplsArgs

    assert FpsArgs.argument_spec["state"]["choices"] == ["merged", "deleted"]
    assert MplsArgs.argument_spec["state"]["choices"] == ["merged", "deleted"]

    # Called directly with the unreachable state, the branch does work.
    instance = make_config_instance(Fps, [], "gathered")
    with patch.object(Fps, "get_facts", side_effect=[copy.deepcopy(BEFORE), copy.deepcopy(BEFORE)]):
        result = instance.execute_module()
    instance._module._connection.edit_config.assert_not_called()
    assert result == {"changed": False, "before": BEFORE, "gathered": BEFORE}


def test_config_is_diff_is_plain_inequality():
    assert config_is_diff([], []) is False
    assert config_is_diff([{"a": 1}], [{"a": 1}]) is False
    assert config_is_diff([{"a": 1}], [{"a": "1"}]) is True, "type differences count as a diff"
    assert config_is_diff([{"a": 1}, {"b": 2}], [{"b": 2}, {"a": 1}]) is True, "list order counts as a diff"


# ---------------------------------------------------------------------------
# c. Facts from a fixture (``data=`` seam)
# ---------------------------------------------------------------------------


def populate_fps_facts(xml):
    facts = FpsFacts(MagicMock())
    return facts.populate_facts(connection=MagicMock(), ansible_facts={"ansible_network_resources": {}}, data=fromstring(xml.encode()))


def test_fps_facts_from_fixture_renders_golden_dict():
    """The parser's xpath is ``//fps/fps``: items are matched as ``<fps><fps>``.
    Scalars are coerced by the argspec (``mtu-size`` -> int)."""
    xml = (
        f'<fps xmlns="{FPS_NS}">'
        "<fps><name>fp1</name><logical-port>1</logical-port><mtu-size>1500</mtu-size><admin-state>enabled</admin-state></fps>"
        "<fps><name>fp2</name><fd-name>fd1</fd-name></fps>"
        "</fps>"
    )
    result = populate_fps_facts(xml)
    assert result == {
        "ansible_network_resources": {
            "fps": [
                {"name": "fp1", "logical_port": "1", "mtu_size": 1500, "admin_state": "enabled"},
                {"name": "fp2", "fd_name": "fd1"},
            ]
        }
    }


def test_fps_facts_accepts_rpc_reply_data_wrapper():
    xml = f'<data><fps xmlns="{FPS_NS}"><fps><name>fp1</name></fps></fps></data>'
    assert populate_fps_facts(xml)["ansible_network_resources"] == {"fps": [{"name": "fp1"}]}


def test_fps_facts_round_trip_into_want_in_have_comparison():
    """Facts output must compare equal to argspec-shaped ``want`` for idempotency."""
    xml = f'<fps xmlns="{FPS_NS}"><fps><name>fp1</name><logical-port>1</logical-port><mtu-size>1500</mtu-size></fps></fps>'
    have = populate_fps_facts(xml)["ansible_network_resources"]["fps"]
    want = [{"name": "fp1", "logical_port": "1", "mtu_size": 1500}]
    config, xml_out = run_pipeline(Fps, want, have, state="merged")
    assert config == [] and xml_out is None


def test_characterize_fps_facts_ignore_the_fp_item_name_the_config_side_emits():
    """Config emits ``<fps><fp>`` (``XML_ITEMS = "fp"``) but facts match
    ``//fps/fps``. Fed the config side's own output shape, the parser returns
    nothing. Which shape the device actually returns is NOT verified offline."""
    assert fps_config.XML_ITEMS == "fp"
    xml = f'<fps xmlns="{FPS_NS}"><fp><name>fp1</name><logical-port>1</logical-port></fp></fps>'
    assert populate_fps_facts(xml) == {"ansible_network_resources": {}}


def test_characterize_fps_facts_drop_nested_lists():
    """``recursive_config_fill`` only walks dict/scalar spec entries, so a
    list-of-dict leaf such as ``normalized_vid`` never makes it into facts.
    Consequence: a ``want`` carrying ``normalized_vid`` can never equal
    ``have``, so merged is never idempotent for such items."""
    xml = f'<fps xmlns="{FPS_NS}"><fps><name>fp1</name><normalized-vid><tag>1</tag><vlan-id>100</vlan-id></normalized-vid></fps></fps>'
    have = populate_fps_facts(xml)["ansible_network_resources"]["fps"]
    assert have == [{"name": "fp1"}]
    want = [{"name": "fp1", "normalized_vid": [{"tag": 1, "vlan_id": 100}]}]
    config, _xml = run_pipeline(Fps, want, have, state="merged")
    assert config == want, "re-sent on every run"


def test_characterize_fps_facts_empty_element_falls_through_to_live_get():
    """``if not data:`` is falsy for an lxml element with no children, so an
    empty ``<fps/>`` passed via ``data=`` still triggers a device ``get``."""
    sentinel = fromstring(f'<fps xmlns="{FPS_NS}"><fps><name>from-device</name></fps></fps>'.encode())
    with patch.object(fps_facts_module, "get", return_value=sentinel) as get:
        result = populate_fps_facts(f'<fps xmlns="{FPS_NS}"/>')
    get.assert_called_once()
    assert result["ansible_network_resources"] == {"fps": [{"name": "from-device"}]}


# ---------------------------------------------------------------------------
# d. Bug-pinning characterization tests (assert current behaviour)
# ---------------------------------------------------------------------------


def test_characterize_ptps_state_deleted_raises_keyerror_on_argspec_key():
    """argspec/facts key is ``ptp_id``; ``_state_deleted`` reads ``config["ptp-id"]``."""
    assert "ptp_id" in PtpsArgs.argument_spec["config"]["options"]
    assert PtpsArgs.argument_spec["state"]["choices"] == ["merged", "deleted"]
    instance = make_config_instance(Ptps, [{"ptp_id": "1"}], "deleted")
    with pytest.raises(KeyError):
        instance.set_config(have=[{"ptp_id": "1"}])


def test_characterize_logical_ports_deleted_is_unreachable_via_argspec():
    assert LogicalPortsArgs.argument_spec["state"]["choices"] == ["merged"]
    # The code path itself works if reached.
    instance = make_config_instance(LogicalPorts, [{"name": "1"}], "deleted")
    config = instance.set_config(have=[{"name": "1"}])
    assert config == [{"name": "1", "operation": "delete"}]
    assert 'operation="delete"' in instance._create_xml_config_generic(config)


def test_characterize_create_xml_config_from_list_mutates_caller_items():
    instance = make_config_instance(Fps, [], "deleted")
    items = [{"name": "fp1", "operation": "delete"}]
    first = instance.create_xml_config_from_list(items)
    assert 'operation="delete"' in first
    assert items == [{"name": "fp1"}], "operation was popped from the caller's dict"
    second = instance.create_xml_config_from_list(items)
    assert 'operation="delete"' not in second


@pytest.mark.xfail(strict=True, reason="create_xml_config_from_list pops 'operation' from caller dicts; flips to XPASS-failure when fixed")
def test_create_xml_config_from_list_should_not_mutate_caller_items():
    instance = make_config_instance(Fps, [], "deleted")
    items = [{"name": "fp1", "operation": "delete"}]
    instance.create_xml_config_from_list(items)
    assert items == [{"name": "fp1", "operation": "delete"}]


def test_characterize_double_colon_namespaces():
    assert "::" in logical_ports_config.NAMESPACE
    assert "::" in classifiers_config.NAMESPACE
    assert logical_ports_config.NAMESPACE == "urn:ciena:params:xml:ns:yang:ciena-pn::ciena-mef-logical-port"
    assert classifiers_config.NAMESPACE == "urn:ciena:params:xml:ns:yang:ciena-pn::ciena-mef-classifier"
    assert "::" not in fps_config.NAMESPACE
    assert "::" not in fds_config.NAMESPACE
    assert fps_config.NAMESPACE == FPS_NS
    assert fds_config.NAMESPACE == "urn:ciena:params:xml:ns:yang:ciena-pn:ciena-mef-fd"
