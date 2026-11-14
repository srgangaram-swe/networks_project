"""Small stateful Linux stand-in for portable ownership and rollback tests."""

import json
from pathlib import Path

from src.processes import CommandResult


def profile(root):
    return {
        "schema_version": 1,
        "roles": {
            "client": {"host": "local", "repository": str(root), "interfaces": {"eth0": "client0"}},
            "router": {
                "host": "local",
                "repository": str(root),
                "interfaces": {"to-client": "router0", "to-server": "router1"},
            },
            "server": {"host": "local", "repository": str(root), "interfaces": {"eth0": "server0"}},
        },
    }


class Kernel:
    def __init__(self):
        self.links = {
            name: {
                "ifname": name,
                "ifindex": i + 10,
                "address": f"02:00:00:00:00:{i:02x}",
                "mtu": 1500,
                "flags": [],
                "addr_info": [],
                "link_type": "ether",
            }
            for i, name in enumerate(("client0", "router0", "router1", "server0"))
        }
        self.namespaces, self.identities, self.calls = {}, {}, []
        self.routes, self.pids = [], {}
        self.queues = [{"kind": "noqueue", "handle": "0:"}]

    def __call__(self, command, **kwargs):
        args = tuple(command)
        self.calls.append(args)
        if args[:3] == ("ip", "netns", "exec"):
            return self._inside(args[3], args[4:])
        if args[:2] == ("ip", "netns"):
            return self._namespace(args[2:])
        if args[:3] == ("ip", "link", "set"):
            name, _, target = args[3:]
            self.namespaces[target][name] = self.links.pop(name)
            return CommandResult(0, b"", b"")
        if "route" in args:
            return self._json(self.routes)
        if args[:3] == ("ip", "-j", "address"):
            return self._json([self.links[args[-1]]])
        if args[:2] == ("ethtool", "-k"):
            return CommandResult(
                0,
                b"tcp-segmentation-offload: on\n"
                b"generic-segmentation-offload: on\n"
                b"generic-receive-offload: off\n"
                b"large-receive-offload: off [fixed]\n",
                b"",
            )
        if args[:3] == ("tc", "-j", "qdisc"):
            return self._json(self.queues)
        if args[:3] == ("ip", "-j", "link"):
            return self._json([self.links[args[-1]]])
        raise AssertionError(args)

    def _namespace(self, args):
        operation, name = args[:2]
        if operation in {"add", "attach"}:
            self.namespaces[name] = self.links if operation == "attach" else {}
            self.identities[name] = [1, len(self.identities) + 100]
        elif operation == "pids":
            return CommandResult(0, self.pids.get(name, b""), b"")
        elif operation == "delete":
            del self.namespaces[name]
            del self.identities[name]
        return CommandResult(0, b"", b"")

    def _inside(self, namespace, args):
        links = self.namespaces[namespace]
        if args[:3] == ("ip", "-j", "link"):
            return self._json(list(links.values()))
        if args[:3] == ("tc", "-j", "qdisc"):
            return self._json(self.queues)
        if args[:3] == ("ip", "link", "set"):
            name, operation, *values = args[3:]
            if operation == "name":
                links[values[0]] = links.pop(name)
                links[values[0]]["ifname"] = values[0]
            elif operation == "netns":
                self.namespaces[values[0]][name] = links.pop(name)
            elif operation == "mtu":
                links[name]["mtu"] = int(values[0])
        return CommandResult(0, b"", b"")

    @staticmethod
    def _json(value):
        return CommandResult(0, json.dumps(value).encode(), b"")


def source():
    return {"commit": "1" * 40, "tree_sha256": "2" * 64, "dirty": False}


ROOT = Path(__file__).resolve().parents[2]
