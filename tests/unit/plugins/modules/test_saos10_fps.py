# Copyright 2026 Ciena Corp
# GNU General Public License v3.0+
# (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Offline characterization tests for saos10_fps.

The golden XML fixtures were produced by running the module against the
mocked connection; they pin the exact ``edit_config`` payload per state.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type


import re

from ansible_collections.ciena.saos10.plugins.modules import saos10_fps
from ansible_collections.ciena.saos10.tests.unit.plugins.modules.saos10_module import (
    TestSaos10Module,
    load_fixture,
    normalize_xml,
)

ENTRY = "fp"

WANT = [{"name": "foo", "fd_name": "foo", "logical_port": "1", "mtu_size": 1522}]

# Facts parsed from fixtures/fps_running.xml (what ``before``/``gathered`` should show).
FACTS = [{"name": "foo", "fd_name": "foo", "logical_port": "1", "mtu_size": 1522}]


class TestSaos10Fps(TestSaos10Module):
    module = saos10_fps
    resource = "fps"

    def test_merged_pushes_golden_xml(self):
        self.queue_replies("fps_empty.xml", "fps_running.xml")
        self.execute_module({"config": WANT, "state": "merged"})
        self.assert_edit_config_xml("fps_merged.xml")

    def test_merged_reports_changed_before_after(self):
        self.queue_replies("fps_empty.xml", "fps_running.xml")
        result = self.execute_module({"config": WANT, "state": "merged"})
        assert result["changed"] is True
        assert result["before"] == []
        assert result["after"] == FACTS

    def test_merged_check_mode_never_edits(self):
        self.queue_replies("fps_empty.xml", "fps_empty.xml")
        self.execute_module({"config": WANT, "state": "merged", "_ansible_check_mode": True})
        self.assert_no_edit_config()

    def test_merged_idempotent(self):
        self.queue_replies("fps_running.xml", "fps_running.xml")
        result = self.execute_module({"config": WANT, "state": "merged"})
        assert result["changed"] is False
        assert result["before"] == FACTS
        self.assert_no_edit_config()

    def test_deleted_pushes_golden_xml(self):
        self.queue_replies("fps_running.xml", "fps_empty.xml")
        self.execute_module({"config": [{"name": "foo"}], "state": "deleted"})
        self.assert_edit_config_xml("fps_deleted.xml")

    def test_deleted_reports_changed_before_after(self):
        self.queue_replies("fps_running.xml", "fps_empty.xml")
        result = self.execute_module({"config": [{"name": "foo"}], "state": "deleted"})
        assert result["changed"] is True
        assert result["before"] == FACTS
        assert result["after"] == []

    def test_deleted_check_mode_never_edits(self):
        self.queue_replies("fps_running.xml", "fps_running.xml")
        self.execute_module(
            {
                "config": [{"name": "foo"}],
                "state": "deleted",
                "_ansible_check_mode": True,
            }
        )
        self.assert_no_edit_config()

    def test_deleted_idempotent(self):
        self.queue_replies("fps_empty.xml", "fps_empty.xml")
        result = self.execute_module({"config": [{"name": "foo"}], "state": "deleted"})
        assert result["changed"] is False
        self.assert_no_edit_config()

    # --- offline / read-only states -------------------------------------

    def test_rendered_equals_merged_xml(self):
        result = self.execute_module({"config": WANT, "state": "rendered"})
        assert result["changed"] is False
        assert normalize_xml(result["rendered"]) == normalize_xml(load_fixture("fps_merged.xml"))
        self.assert_offline()

    def test_parsed_returns_facts(self):
        result = self.execute_module({"running_config": load_fixture("fps_running.xml"), "state": "parsed"})
        assert result["changed"] is False
        assert result["parsed"] == FACTS
        self.assert_offline()

    def test_parsed_accepts_bare_resource_root(self):
        bare = re.search(r"<fps\b.*</fps>", load_fixture("fps_running.xml"), re.S).group(0)
        result = self.execute_module({"running_config": bare, "state": "parsed"})
        assert result["parsed"] == FACTS
        self.assert_offline()

    def test_parsed_does_not_resolve_external_entities(self):
        xml = ('<!DOCTYPE data [<!ENTITY xxe SYSTEM "file:///etc/hostname">]>' '<data><fps xmlns="urn:x"><{}><name>&xxe;</name></{}></fps></data>').format(
            ENTRY, ENTRY
        )
        result = self.execute_module({"running_config": xml, "state": "parsed"}, failed=True)
        assert "xxe" in result["msg"]
        assert open("/etc/hostname").read().strip() not in str(result)
        self.assert_offline()

    def test_parsed_empty_reply_returns_empty_list(self):
        result = self.execute_module({"running_config": load_fixture("fps_empty.xml"), "state": "parsed"})
        assert result["parsed"] == []
        self.assert_offline()

    def test_gathered_returns_facts_without_editing(self):
        self.queue_replies("fps_running.xml")
        result = self.execute_module({"state": "gathered"})
        assert result["changed"] is False
        assert result["gathered"] == FACTS
        assert len(self.get_calls) == 1
        self.assert_no_edit_config()

    def test_parsed_requires_running_config(self):
        result = self.execute_module({"state": "parsed"}, failed=True)
        assert "running_config" in result["msg"]
        self.assert_offline()

    def test_rendered_requires_config(self):
        result = self.execute_module({"running_config": load_fixture("fps_running.xml"), "state": "rendered"}, failed=True)
        assert "config" in result["msg"]
        self.assert_offline()

    def test_config_and_running_config_are_mutually_exclusive(self):
        result = self.execute_module(
            {"config": WANT, "running_config": load_fixture("fps_running.xml"), "state": "rendered"},
            failed=True,
        )
        assert "mutually exclusive" in result["msg"]
        self.assert_offline()
