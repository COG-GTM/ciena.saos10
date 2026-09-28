# Copyright 2026 Ciena Corp
# GNU General Public License v3.0+
# (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Offline characterization tests for saos10_fps.

The golden XML fixtures were produced by running the module against the
mocked connection; they pin the exact ``edit_config`` payload per state.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

from ansible_collections.ciena.saos10.plugins.modules import saos10_fps
from ansible_collections.ciena.saos10.tests.unit.plugins.modules.saos10_module import (
    TestSaos10Module,
)

WANT = [{"name": "foo", "fd_name": "foo", "logical_port": "1", "mtu_size": 1522}]

# Facts parsed from fixtures/fps_running.xml (what ``before``/``gathered`` should show).
FACTS = [{"name": "foo", "fd_name": "foo", "logical_port": "1", "mtu_size": 1522}]

# Behaviour that the current code does not deliver yet (see reason); flipped
# to a hard pass once the facts xpath and the merged/deleted comparisons are fixed.
KNOWN_GAP = pytest.mark.xfail(
    strict=True,
    reason="facts xpath //fps/fps never matches a device reply, so have is always empty",
)

CHECK_MODE_GAP = pytest.mark.xfail(
    strict=True,
    reason="supports_check_mode=True but edit_config is still called in check mode",
)


class TestSaos10Fps(TestSaos10Module):
    module = saos10_fps
    resource = "fps"

    def test_merged_pushes_golden_xml(self):
        self.queue_replies("fps_empty.xml", "fps_running.xml")
        self.execute_module({"config": WANT, "state": "merged"})
        self.assert_edit_config_xml("fps_merged.xml")

    @KNOWN_GAP
    def test_merged_reports_changed_before_after(self):
        self.queue_replies("fps_empty.xml", "fps_running.xml")
        result = self.execute_module({"config": WANT, "state": "merged"})
        assert result["changed"] is True
        assert result["before"] == []
        assert result["after"] == FACTS

    @CHECK_MODE_GAP
    def test_merged_check_mode_never_edits(self):
        self.queue_replies("fps_empty.xml", "fps_empty.xml")
        self.execute_module({"config": WANT, "state": "merged", "_ansible_check_mode": True})
        self.assert_no_edit_config()

    @KNOWN_GAP
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

    @KNOWN_GAP
    def test_deleted_reports_changed_before_after(self):
        self.queue_replies("fps_running.xml", "fps_empty.xml")
        result = self.execute_module({"config": [{"name": "foo"}], "state": "deleted"})
        assert result["changed"] is True
        assert result["before"] == FACTS
        assert result["after"] == []

    @CHECK_MODE_GAP
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

    @KNOWN_GAP
    def test_deleted_idempotent(self):
        self.queue_replies("fps_empty.xml", "fps_empty.xml")
        result = self.execute_module({"config": [{"name": "foo"}], "state": "deleted"})
        assert result["changed"] is False
        self.assert_no_edit_config()
