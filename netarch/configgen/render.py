"""Plan → Cisco IOS text, `full` and `pt` dialects (technical.md §9.2–9.3).

Templates only render plan fields; dialect differences are flags computed here from the PT
capability matrix, and every `pt` downgrade is listed in a `! NETARCH-PT-COMPAT:` header line.
"""

from __future__ import annotations

import re
import secrets as _secrets
from datetime import UTC, datetime
from functools import cache
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined

from netarch.engines.ptcaps import pt_result
from netarch.engines.vlsm import dotted, mask
from netarch.engines.vpn import crypto_suite
from netarch.models.plan import Device, NetworkPlan

TEMPLATES = {"router": "router.j2", "l3switch": "l3switch.j2", "l2switch": "l2switch.j2"}


@cache
def _env() -> Environment:
    """One compiled template set per process (recompiling per device was the F6 hot spot)."""
    env = Environment(loader=PackageLoader("netarch.configgen", "templates"),
                      undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True,
                      keep_trailing_newline=True, autoescape=False)
    env.filters["mask"] = lambda p: dotted(mask(int(p)))
    return env


def _version() -> str:
    try:
        return version("netarch")
    except PackageNotFoundError:  # pragma: no cover - source checkout without install
        return "dev"


def ios_text(text: str) -> str:
    """Comment-safe text: printable ASCII only, no newlines (no config injection)."""
    return re.sub(r"[^\x20-\x7e]", "?", text)[:80]


def dialect_flags(plan: NetworkPlan, dialect: str) -> tuple[dict[str, Any], list[str]]:
    """Feature switches for the templates, plus the PT-compat lines for the header."""
    full = dialect == "full"
    acl_log = full or pt_result("svi_extended_acl_log") == "accepted"
    qos = full or pt_result("mqc_llq") == "accepted"
    mss = full or pt_result("tunnel_adjust_mss_ip_mtu") == "accepted"
    redist = full or pt_result("prefix_list_route_map_redistribution") == "accepted"
    suite = crypto_suite(dialect)
    compat: list[str] = []
    if not full:
        if not acl_log:
            compat.append("ACL 'log' keyword omitted (PT matrix svi_extended_acl_log="
                          f"{pt_result('svi_extended_acl_log')})")
        if not qos and plan.qos_policies:
            compat.append(f"QoS (MQC/LLQ) block omitted (PT matrix mqc_llq={pt_result('mqc_llq')})")
        if not mss and plan.vpn_tunnels:
            compat.append("tunnel ip mtu / ip tcp adjust-mss omitted (PT matrix "
                          f"tunnel_adjust_mss_ip_mtu={pt_result('tunnel_adjust_mss_ip_mtu')})")
        if plan.vpn_tunnels and suite["hash"] != "sha256":
            compat.append("IPsec uses hash sha / group 5 / esp-sha-hmac (PT matrix "
                          f"ipsec_sha256_group14={pt_result('ipsec_sha256_group14')})")
        if not redist and any(d.ospf and d.ospf.redistribute_bgp for d in plan.devices):
            compat.append("BGP → OSPF redistribution (prefix-list/route-map) omitted (PT matrix "
                          "prefix_list_route_map_redistribution="
                          f"{pt_result('prefix_list_route_map_redistribution')}); only the hub "
                          "reaches the VPC")
        if plan.addressing and plan.addressing.p2p_prefix == 30:
            compat.append("point-to-point links use /30, not /31 (PT matrix /31 rows not "
                          "accepted)")
    return {"acl_log": acl_log, "qos": qos, "tunnel_mss": mss, "redistribute": redist,
            "crypto": suite}, compat


def make_secrets(plan: NetworkPlan) -> dict[str, str]:
    """Random enable/admin passwords and one PSK per tunnel (technical.md §8.4)."""
    out = {"enable": _secrets.token_hex(12), "admin": _secrets.token_hex(12)}
    out |= {t.psk_ref: _secrets.token_hex(16) for t in plan.vpn_tunnels}
    return out


def render_device(plan: NetworkPlan, device: Device, dialect: str, secrets: dict[str, str],
                  *, timestamp: str | None = None) -> str:
    if dialect not in ("pt", "full"):
        raise ValueError(f"unknown dialect {dialect!r}; expected 'pt' or 'full'")
    flags, compat = dialect_flags(plan, dialect)
    acls = [a for a in plan.acl_policies if a.device == device.hostname]
    qos = [q for q in plan.qos_policies if q.device == device.hostname]
    ts = timestamp or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    tpl = _env().get_template(TEMPLATES[device.role])
    text = tpl.render(device=device, dialect=dialect, flags=flags, compat=compat, acls=acls,
                      qos=qos, secrets=secrets, profile=ios_text(plan.requirements.profile_name),
                      version=_version(), timestamp=ts)
    return re.sub(r"\n{3,}", "\n\n", text)


def render_all(plan: NetworkPlan, dialect: str, secrets: dict[str, str] | None = None,
               *, timestamp: str | None = None) -> dict[str, str]:
    """hostname → config text for every device."""
    s = secrets if secrets is not None else make_secrets(plan)
    return {d.hostname: render_device(plan, d, dialect, s, timestamp=timestamp)
            for d in plan.devices}
