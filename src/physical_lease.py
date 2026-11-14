"""Move only blank, dedicated NICs into owned namespaces and journal their return."""

import os
import re
from pathlib import Path

from src.artifacts import atomic_json, parse_json, read_json
from src.physical_profile import role_path
from src.processes import run_command
from src.topology import Topology
from src.topology_runtime import namespace_identity, require_linux


def inspect_interfaces(item: dict) -> list[dict]:
    routes = parse_json(run_command(("ip", "-j", "route", "show", "table", "all")).stdout)
    ipv6 = parse_json(run_command(("ip", "-j", "-6", "route", "show", "table", "all")).stdout)
    routed = _routed_interfaces(routes + ipv6)
    result = []
    for canonical, name in item["interfaces"].items():
        links = parse_json(run_command(("ip", "-j", "address", "show", "dev", name)).stdout)
        if len(links) != 1:
            raise ValueError("dedicated interface was not uniquely found")
        link = links[0]
        if name in routed or link.get("addr_info") or "UP" in link.get("flags", []):
            raise PermissionError(
                f"interface {name} must be down, address-free, and unused by routes"
            )
        if link.get("master") or link.get("link_type") != "ether":
            raise PermissionError("dedicated interfaces cannot be enslaved or non-Ethernet")
        queues = parse_json(run_command(("tc", "-j", "qdisc", "show", "dev", name)).stdout)
        if any(q.get("handle") != "0:" for q in queues):
            raise PermissionError("dedicated interfaces must have only kernel-default queues")
        features = run_command(("ethtool", "-k", name), limit=16384).stdout.decode()
        offloads = {}
        for short, long in (
            ("tso", "tcp-segmentation-offload"),
            ("gso", "generic-segmentation-offload"),
            ("gro", "generic-receive-offload"),
            ("lro", "large-receive-offload"),
        ):
            match = re.search(rf"^{long}: (on|off)(?: |$)", features, re.MULTILINE)
            if match is None:
                raise ValueError("cannot retain original offload settings")
            offloads[short] = match.group(1)
        result.append(
            {
                "original": name,
                "ifindex": link["ifindex"],
                "canonical": canonical,
                "mac": link["address"],
                "mtu": link["mtu"],
                "offloads": offloads,
            }
        )
    return result


def _routed_interfaces(routes):
    return {row.get("dev") for row in routes} | {
        hop.get("dev") for row in routes for hop in row.get("nexthops", [])
    }


class PhysicalLease:
    def __init__(self, directory: Path, state: dict):
        self.directory = directory
        self.state = state

    @classmethod
    def load(cls, item: dict, role: str, token: str):
        directory = role_path(item, token, role)
        info = directory.lstat()
        if directory.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError(
                "physical journal must be private and owned by the effective user"
            )
        state = read_json(directory / "lease.json", 65536)
        if (state["role"], state["token"], state["interfaces"]) != (
            role,
            token,
            item["interfaces"],
        ):
            raise ValueError("physical journal does not match its profile")
        topology = Topology(token)
        expected = {topology.namespace(role), f"np-{token}-return-{role}"}
        if (
            state["namespace"] != topology.namespace(role)
            or state["return_namespace"] not in expected
        ):
            raise ValueError("unexpected physical namespace names")
        if not isinstance(state["owned"], dict) or not set(state["owned"]) <= expected:
            raise ValueError("unexpected owned physical resources")
        return cls(directory, state)

    @classmethod
    def prepare(cls, item: dict, role: str, token: str):
        require_linux()
        links = inspect_interfaces(item)
        topology = Topology(token)
        directory = role_path(item, token, role)
        directory.mkdir(mode=0o700)
        state = {
            "role": role,
            "token": token,
            "interfaces": item["interfaces"],
            "namespace": topology.namespace(role),
            "return_namespace": f"np-{token}-return-{role}",
            "owned": {},
            "links": links,
            "phase": "preparing",
        }
        lease = cls(directory, state)
        lease.save()
        try:
            lease._create_namespace(state["return_namespace"], attach=True)
            lease._create_namespace(state["namespace"])
            for link in links:
                run_command(("ip", "link", "set", link["original"], "netns", state["namespace"]))
                lease.execute(("ip", "link", "set", link["original"], "name", link["canonical"]))
            state["phase"] = "active"
            lease.save()
        except BaseException as primary:
            try:
                lease.cleanup()
            except (OSError, ValueError, RuntimeError) as cleanup:
                primary.add_note(f"physical setup cleanup also failed: {cleanup}")
            raise
        return lease

    def _create_namespace(self, name, attach=False):
        if namespace_identity(name) is not None:
            raise FileExistsError("physical namespace already exists")
        command = (
            ("ip", "netns", "attach", name, str(os.getpid()))
            if attach
            else ("ip", "netns", "add", name)
        )
        run_command(command)
        identity = namespace_identity(name)
        if identity is None:
            raise RuntimeError("namespace creation was not observable")
        self.state["owned"][name] = identity
        self.save()

    def save(self):
        atomic_json(self.directory / "lease.json", self.state)

    def verify(self):
        for name, identity in self.state["owned"].items():
            if namespace_identity(name) != identity:
                raise PermissionError("physical namespace identity changed")

    def execute(self, args, **kwargs):
        self.verify()
        return run_command(("ip", "netns", "exec", self.state["namespace"], *args), **kwargs)

    def _return_link(self, link):
        rows = parse_json(self.execute(("ip", "-j", "link", "show")).stdout)
        matches = [
            row
            for row in rows
            if row.get("address") == link["mac"]
            and row["ifname"] in {link["canonical"], link["original"]}
        ]
        if not matches:
            restored = parse_json(
                run_command(("ip", "-j", "link", "show", "dev", link["original"])).stdout
            )
            if len(restored) != 1 or restored[0].get("address") != link["mac"]:
                raise PermissionError("cannot identify the interface being returned")
            return
        if len(matches) != 1:
            raise PermissionError("physical interface identity is ambiguous")
        name = matches[0]["ifname"]
        self.execute(("ip", "link", "set", name, "down"))
        self.execute(("ip", "address", "flush", "dev", name))
        self.execute(("ip", "-6", "address", "flush", "dev", name))
        self._clear_queues(name)
        options = tuple(value for pair in link["offloads"].items() for value in pair)
        self.execute(("ethtool", "-K", name, *options))
        self.execute(("ip", "link", "set", name, "mtu", str(link["mtu"])))
        if name != link["original"]:
            self.execute(("ip", "link", "set", name, "name", link["original"]))
        self.execute(
            ("ip", "link", "set", link["original"], "netns", self.state["return_namespace"])
        )

    def _clear_queues(self, name):
        queues = parse_json(self.execute(("tc", "-j", "qdisc", "show", "dev", name)).stdout)
        for queue in queues:
            if queue["kind"] in {"clsact", "ingress"}:
                self.execute(("tc", "qdisc", "del", "dev", name, queue["kind"]))
            elif queue.get("root") and queue.get("handle") != "0:":
                self.execute(("tc", "qdisc", "del", "dev", name, "root"))

    def cleanup(self):
        require_linux()
        self.verify()
        self.state["phase"] = "closing"
        self.save()
        namespace = self.state["namespace"]
        if namespace in self.state["owned"]:
            if run_command(("ip", "netns", "pids", namespace)).stdout.strip():
                raise RuntimeError(
                    "physical namespace still contains live processes; retain journal"
                )
            for link in self.state["links"]:
                self._return_link(link)
            run_command(("ip", "netns", "delete", namespace))
            del self.state["owned"][namespace]
            self.save()
        target = self.state["return_namespace"]
        if target in self.state["owned"]:
            run_command(("ip", "netns", "delete", target))
            del self.state["owned"][target]
        self.state["phase"] = "closed"
        self.save()
