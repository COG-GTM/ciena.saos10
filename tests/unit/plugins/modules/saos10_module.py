# Copyright 2026 Ciena Corp
# GNU General Public License v3.0+
# (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Shared offline harness for the SAOS 10 NETCONF resource modules.

No device is involved: the NETCONF ``get`` used by the facts classes is
replaced with a stub that returns fixture XML, and the resource connection
used by the config classes is replaced with a ``MagicMock`` so that every
``edit_config`` call is captured for assertion.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import os
import re

from unittest.mock import MagicMock, patch

from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes

from lxml.etree import fromstring

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

NC_CONFIG_OPEN = '<nc:config xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">'
NC_CONFIG_CLOSE = "</nc:config>"

_FACTS_GET = "ansible_collections.ciena.saos10.plugins.module_utils.network.saos10.facts.{0}.{0}.get"
_CFG_CONNECTION = "ansible_collections.ansible.netcommon.plugins.module_utils.network.common.cfg.base.get_resource_connection"


def load_fixture(name):
    """Return the text of ``fixtures/<name>``."""
    with open(os.path.join(FIXTURE_DIR, name)) as handle:
        return handle.read()


def normalize_xml(text):
    """Collapse inter-element and surrounding whitespace so that pretty-printed
    golden files compare equal to the compact XML produced by lxml."""
    text = re.sub(r">\s+<", "><", text.strip())
    return re.sub(r"\s+", " ", text)


def set_module_args(args):
    """Expose ``args`` to the next ``AnsibleModule`` instance."""
    encoded = to_bytes(json.dumps({"ANSIBLE_MODULE_ARGS": args}))
    basic._ANSIBLE_ARGS = encoded
    if hasattr(basic, "_ANSIBLE_PROFILE"):
        basic._ANSIBLE_PROFILE = "legacy"


class AnsibleExitJson(Exception):
    """Raised in place of ``AnsibleModule.exit_json``."""


class AnsibleFailJson(Exception):
    """Raised in place of ``AnsibleModule.fail_json``."""


def exit_json(*args, **kwargs):
    kwargs.setdefault("changed", False)
    raise AnsibleExitJson(kwargs)


def fail_json(*args, **kwargs):
    kwargs["failed"] = True
    raise AnsibleFailJson(kwargs)


class TestSaos10Module(object):
    """Base class for one resource module.

    Subclasses set ``module`` (the imported ``saos10_<resource>`` module)
    and ``resource`` (the facts package name, e.g. ``"fps"``).
    """

    module = None
    resource = None

    def setup_method(self):
        self.connection = MagicMock(name="resource_connection")
        self.get_replies = []
        self.get_calls = []
        self.connection_requests = 0

        def fake_get(module, *args, **kwargs):
            self.get_calls.append((args, kwargs))
            if not self.get_replies:
                raise AssertionError("unexpected NETCONF <get>: no fixture reply queued")
            reply = self.get_replies.pop(0)
            return fromstring(to_bytes(reply))

        def fake_resource_connection(module):
            self.connection_requests += 1
            module._connection = self.connection
            return self.connection

        self._patches = [
            patch.multiple(basic.AnsibleModule, exit_json=exit_json, fail_json=fail_json),
            patch(_FACTS_GET.format(self.resource), side_effect=fake_get),
            patch(_CFG_CONNECTION, side_effect=fake_resource_connection),
        ]
        for item in self._patches:
            item.start()

    def teardown_method(self):
        for item in reversed(self._patches):
            item.stop()
        basic._ANSIBLE_ARGS = None

    def queue_replies(self, *fixtures):
        """Queue the fixture files returned by successive NETCONF <get> calls."""
        self.get_replies.extend(load_fixture(name) for name in fixtures)

    def execute_module(self, args, failed=False):
        set_module_args(args)
        if failed:
            with self._raises(AnsibleFailJson) as exc:
                self.module.main()
            result = exc.args[0]
            assert result["failed"] is True, result
        else:
            with self._raises(AnsibleExitJson) as exc:
                self.module.main()
            result = exc.args[0]
        return result

    class _raises(object):
        def __init__(self, exc_type):
            self.exc_type = exc_type
            self.args = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc_type is None:
                raise AssertionError("module did not call exit_json/fail_json")
            if not issubclass(exc_type, self.exc_type):
                return False
            self.args = exc.args
            return True

    def edit_config_payloads(self):
        """Return the ``config`` argument of every captured ``edit_config``."""
        return [call.kwargs["config"] for call in self.connection.edit_config.call_args_list]

    def assert_edit_config_xml(self, golden_fixture):
        payloads = self.edit_config_payloads()
        assert len(payloads) == 1, payloads
        expected = NC_CONFIG_OPEN + normalize_xml(load_fixture(golden_fixture)) + NC_CONFIG_CLOSE
        assert normalize_xml(payloads[0]) == expected
        self.connection.edit_config.assert_called_once_with(config=payloads[0], target="running")

    def assert_no_edit_config(self):
        self.connection.edit_config.assert_not_called()

    def assert_offline(self):
        """The module never asked for a connection nor issued a NETCONF <get>."""
        assert self.connection_requests == 0
        assert self.get_calls == []
        assert self.connection.method_calls == []
