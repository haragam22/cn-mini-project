"""GRE-over-IPsec tunnels (technical.md §8.4, RT.R4). Pure: plan in, plan out.

Tunnel subnets come from the P3 infra block (`tunnel:<hub>--<site>` rows); outer addresses are
the routers' Internet interfaces. PSKs are referenced here (`psk:<tunnel>`) and generated at
export, so the plan stays deterministic.
"""

from __future__ import annotations

from netarch.engines.optics import load_data, value
from netarch.engines.ptcaps import pt_result
from netarch.engines.vlsm import dotted, first_host, last_host
from netarch.explain.builder import decision_id, make_decision, rejected
from netarch.models.plan import Crypto, CryptoPeer, Interface, NetworkPlan, VpnTunnel
from netarch.models.requirements import parse_cidr

CRYPTO_FULL = {"encr": "aes 256", "hash": "sha256", "group": 14,
               "transform": "esp-aes 256 esp-sha256-hmac"}
CRYPTO_PT_FALLBACK = {"encr": "aes 256", "hash": "sha", "group": 5,
                      "transform": "esp-aes 256 esp-sha-hmac"}


def crypto_suite(dialect: str) -> dict[str, object]:
    """full → SHA-256/group 14; pt → the same only if the PT matrix accepted it (§8.4)."""
    if dialect == "full" or pt_result("ipsec_sha256_group14") == "accepted":
        return dict(CRYPTO_FULL)
    return dict(CRYPTO_PT_FALLBACK)


def _public(plan: NetworkPlan, host: str) -> Interface:
    return next(i for i in plan.device(host).interfaces if i.description == "Internet (public)")


def run(plan: NetworkPlan) -> NetworkPlan:
    req = plan.requirements
    ap = plan.addressing
    rows = [r for r in ap.subnets if r.kind == "p2p" and r.name.startswith("tunnel:")] if ap \
        else []
    if not rows:
        return plan
    design = load_data("design.yaml")
    mtu, mss = value(design, "tunnel_ip_mtu"), value(design, "tunnel_tcp_mss")
    devices = {d.hostname: d.model_copy(deep=True) for d in plan.devices}
    site_host = {d.site: d.hostname for d in plan.devices if d.role in ("router", "l3switch")}
    site_host["cloud-vgw"] = "cloud-vgw"
    tunnels: list[VpnTunnel] = []
    peers: dict[str, list[CryptoPeer]] = {}
    for i, r in enumerate(rows, start=1):
        a_site, b_site = r.name.removeprefix("tunnel:").split("--")
        a, b = site_host[a_site], site_host[b_site]
        net, p, _ = parse_cidr(r.cidr)
        pa, pb = _public(plan, a), _public(plan, b)
        bgp = b == "cloud-vgw"
        ref = f"psk:{r.name.removeprefix('tunnel:')}"
        tif = f"Tunnel{i}"
        for host, ip, src, dst, other in ((a, first_host(net, p), pa, pb, b),
                                          (b, last_host(net, p), pb, pa, a)):
            dev = devices[host]
            dev.interfaces.append(Interface(
                name=tif, kind="tunnel", ip=dotted(ip), prefix=p, subnet=r.cidr,
                description=f"GRE/IPsec to {other}", tunnel_source=src.name,
                tunnel_destination=dst.ip, ip_mtu=mtu, tcp_mss=mss, peer=f"{other}:{tif}"))
            peers.setdefault(host, []).append(CryptoPeer(
                seq=10 * (len(peers.get(host, [])) + 1), peer_ip=dst.ip or "",
                acl=f"GRE-{other.upper()}", acl_entry=f"permit gre host {src.ip} host {dst.ip}",
                psk_ref=ref))
        tunnels.append(VpnTunnel(name=r.name.removeprefix("tunnel:"), a=a, b=b, subnet=r.cidr,
                                 a_if=tif, b_if=tif, a_public=pa.ip or "", b_public=pb.ip or "",
                                 psk_ref=ref, routing="bgp" if bgp else "ospf"))
    for host, ps in peers.items():
        pub = _public(plan, host)
        devices[host].crypto = Crypto(map_name="CMAP", interface=pub.name, peers=ps)
        devices[host].interfaces = [x.model_copy(update={"crypto_map": "CMAP"})
                                    if x.name == pub.name else x
                                    for x in devices[host].interfaces]
    plan = plan.model_copy(update={"devices": list(devices.values()), "vpn_tunnels": tunnels})
    return _decisions(plan, req.target_dialect, mtu, mss)


def _decisions(plan: NetworkPlan, dialect: str, mtu: int, mss: int) -> NetworkPlan:
    std = load_data("standards.yaml")
    n0 = sum(d.id.startswith("VPN-") for d in plan.decisions)
    t = plan.vpn_tunnels
    ospf_t = [x.name for x in t if x.routing == "ospf"]
    d1 = make_decision(
        id=decision_id("VPN", n0 + 1), domain="vpn", subject="Inter-site transport over the "
        "Internet", choice=f"GRE-over-IPsec, {len(t)} tunnels (hub and spoke)", rule_id="RT.R4",
        inputs={"tunnels": len(t), "ospf_tunnels": len(ospf_t), "ip_mtu": mtu, "tcp_mss": mss},
        math=[f"tunnels: {', '.join(x.name for x in t)}",
              "GRE adds 24 B; ESP adds about 50–73 B; 1500 − 24 − 73 = 1403 → ip mtu "
              f"{mtu}",
              f"tcp adjust-mss = {mtu} − 20 (IP) − 20 (TCP) = {mss}"],
        standards=[std["rfc_2784"], std["rfc_4301"], std["rfc_2409"]],
        rejected=[rejected("plain policy-based IPsec (no GRE)",
                           "carries no multicast, so OSPF hellos (224.0.0.5) never cross"),
                  rejected("DMVPN", "needs NHRP/mGRE, which Packet Tracer 2911 does not run")],
        counterfactual="Would drop GRE if sites were joined by private circuits (no Internet).",
    )
    suite = crypto_suite(dialect)
    full = suite == CRYPTO_FULL
    d2 = make_decision(
        id=decision_id("VPN", n0 + 2), domain="vpn", subject="IPsec crypto suite",
        choice=f"IKEv1 crypto map: {suite['encr']}, hash {suite['hash']}, DH group "
               f"{suite['group']}, {suite['transform']}",
        rule_id="VPN.CRYPTO",
        inputs={"target_dialect": dialect,
                "pt_ipsec_sha256_group14": pt_result("ipsec_sha256_group14")},
        math=["DH group 14 = 2048-bit MODP; group 5 = 1536-bit",
              "pre-shared keys: one random key per tunnel, generated at export (secrets.txt)"],
        standards=[std["rfc_2409"], std["rfc_4301"]],
        rejected=[rejected("SHA-1 / group 5" if full else "SHA-256 / group 14",
                           "weaker (SHA-1 collisions, 1536-bit DH)" if full else
                           "Packet Tracer acceptance not confirmed in the PT matrix")],
        counterfactual=None if full else "Would use SHA-256/group 14 once the PT matrix row "
        "ipsec_sha256_group14 is accepted, or with the full dialect.",
        warnings=[] if full else ["pt dialect uses SHA-1 / DH group 5 for Packet Tracer only."],
    )
    return plan.model_copy(update={
        "decisions": [*plan.decisions, d1, d2],
        "warnings": [*plan.warnings, *(f"{d2.id}: {w}" for w in d2.warnings)],
    })
