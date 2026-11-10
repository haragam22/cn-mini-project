"""NetworkPlan (technical.md §4.3): the object every engine reads and returns.

Sections are filled by later phases (L1/L2 in P2, addressing in P3, routing/VPN/QoS/ACL in P4).
Serialisable to ``plan.json`` so plans can be diffed in tests.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from netarch.models.decisions import Decision
from netarch.models.requirements import Requirements, Site

_CFG = ConfigDict(extra="forbid")


class OspfIf(BaseModel):
    model_config = _CFG
    area: int
    point_to_point: bool = False
    cost: int | None = None
    hello: int | None = None
    dead: int | None = None


class Interface(BaseModel):
    """One configured interface (technical.md §9.3 order: physical, sub, SVI, loopback, tunnel)."""

    model_config = _CFG
    name: str
    kind: Literal["physical", "sub", "svi", "loopback", "tunnel"]
    mode: Literal["routed", "access", "trunk", "none"] = "routed"
    description: str = ""
    ip: str | None = None
    prefix: int | None = None
    subnet: str | None = None  # planned CIDR the IP must sit in
    vlan: int | None = None  # access VLAN, dot1Q tag of a sub-interface, or SVI VLAN
    allowed_vlans: list[int] = Field(default_factory=list)
    native_vlan: int | None = None
    peer: str | None = None  # "hostname:interface" at the other end of the cable / tunnel
    ospf: OspfIf | None = None
    acl_in: str | None = None
    acl_out: str | None = None
    policy_in: str | None = None
    policy_out: str | None = None
    tunnel_source: str | None = None
    tunnel_destination: str | None = None
    ip_mtu: int | None = None
    tcp_mss: int | None = None
    crypto_map: str | None = None
    edge_port: bool = False  # portfast + bpduguard


class OspfNetwork(BaseModel):
    model_config = _CFG
    network: str
    wildcard: str
    area: int


class OspfProcess(BaseModel):
    model_config = _CFG
    process_id: int = 1
    router_id: str
    reference_bandwidth: int
    networks: list[OspfNetwork] = Field(default_factory=list)
    active_interfaces: list[str] = Field(default_factory=list)  # all others passive
    area_ranges: list[OspfNetwork] = Field(default_factory=list)  # wildcard holds the mask
    redistribute_bgp: str | None = None  # route-map name


class BgpNeighbor(BaseModel):
    model_config = _CFG
    ip: str
    remote_as: int
    description: str = ""


class BgpProcess(BaseModel):
    model_config = _CFG
    asn: int
    router_id: str
    neighbors: list[BgpNeighbor] = Field(default_factory=list)
    networks: list[tuple[str, str]] = Field(default_factory=list)  # (network, mask)


class CryptoPeer(BaseModel):
    model_config = _CFG
    seq: int
    peer_ip: str
    acl: str  # crypto ACL name (extended, permit gre local → peer)
    acl_entry: str
    psk_ref: str  # key into the export's secrets


class Crypto(BaseModel):
    model_config = _CFG
    map_name: str
    interface: str
    peers: list[CryptoPeer]


class Device(BaseModel):
    model_config = _CFG
    hostname: str
    model: str
    role: str  # router | l3switch | l2switch
    site: str
    interfaces: list[Interface] = Field(default_factory=list)
    vlans: dict[int, str] = Field(default_factory=dict)
    stp_root_vlans: list[int] = Field(default_factory=list)
    ip_routing: bool = False
    default_gateway: str | None = None
    ospf: OspfProcess | None = None
    bgp: BgpProcess | None = None
    static_routes: list[tuple[str, str, str]] = Field(default_factory=list)  # net, mask, hop
    prefix_lists: dict[str, list[str]] = Field(default_factory=dict)
    route_maps: dict[str, list[str]] = Field(default_factory=dict)
    acls: list[str] = Field(default_factory=list)  # names of plan.acl_policies on this device
    vty_acl: str | None = None
    crypto: Crypto | None = None
    qos: list[str] = Field(default_factory=list)  # names of plan.qos_policies on this device

    def interface(self, name: str) -> Interface:
        return next(i for i in self.interfaces if i.name == name)


class PlanLink(BaseModel):
    model_config = _CFG
    a: str
    b: str
    media: str | None = None
    optic: str | None = None
    subnet: str | None = None
    ports: dict[str, str] = Field(default_factory=dict)  # hostname -> interface name


class PlanSegment(BaseModel):
    model_config = _CFG
    site: str
    name: str
    vlan: int
    subnet: str | None = None
    gateway: str | None = None


class Subnet(BaseModel):
    """One row of the addressing table (technical.md §7.5)."""

    model_config = _CFG
    kind: Literal["segment", "p2p", "loopback"]
    site: str | None  # None for infra (p2p, loopback) rows
    name: str
    vlan: int | None = None
    network: str
    prefix: int
    mask: str
    wildcard: str
    gateway: str | None = None
    first_host: str
    last_host: str
    broadcast: str
    usable: int
    requested: int  # hosts as given (segments) or addresses used (p2p 2, loopback 1)
    needed: int  # after growth, plus the gateway (segments)
    utilisation_pct: float  # requested ÷ usable

    @property
    def cidr(self) -> str:
        return f"{self.network}/{self.prefix}"


class SiteBlock(BaseModel):
    model_config = _CFG
    site: str
    block: str  # contiguous, aligned; equals the site's summary route
    summary: str
    demand: int  # Σ segment block sizes before rounding the site block


class AddressingPlan(BaseModel):
    model_config = _CFG
    root: str
    p2p_prefix: int
    site_blocks: list[SiteBlock]
    infra_block: str
    org_summary: str
    subnets: list[Subnet]
    loopbacks: dict[str, str]  # site id -> loopback /32 (router-ID)
    free_blocks: list[str]
    metrics: dict[str, Any]


class RoutingDesign(BaseModel):
    model_config = _CFG
    protocol: str | None = None
    process_ids: dict[str, int] = Field(default_factory=dict)
    areas: dict[str, int] = Field(default_factory=dict)
    asns: dict[str, int] = Field(default_factory=dict)
    router_ids: dict[str, str] = Field(default_factory=dict)


class VpnTunnel(BaseModel):
    model_config = _CFG
    name: str
    a: str  # hostname
    b: str
    subnet: str | None = None
    a_if: str = ""
    b_if: str = ""
    a_public: str = ""
    b_public: str = ""
    psk_ref: str = ""
    routing: Literal["ospf", "bgp"] = "ospf"


class QosPolicy(BaseModel):
    model_config = _CFG
    name: str
    device: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class AclEntry(BaseModel):
    model_config = _CFG
    action: Literal["permit", "deny"]
    text: str  # IOS body after the action, e.g. "tcp 10.0.8.0 0.0.1.255 10.0.11.0 0.0.0.63 eq 443"
    log: bool = False  # rendered only where the dialect supports it


class AclPolicy(BaseModel):
    model_config = _CFG
    name: str
    device: str = ""
    kind: Literal["extended", "standard"] = "extended"
    entries: list[AclEntry] = Field(default_factory=list)
    purpose: str = ""


class Cable(BaseModel):
    """One cable in the Packet Tracer lab (technical.md §6.4, §11.3 cabling table)."""

    model_config = _CFG
    a: str
    a_port: str
    b: str
    b_port: str
    kind: Literal["trunk", "routed", "access", "host"]
    physical: str = ""  # the real-world recommendation this lab cable stands for


class EndHost(BaseModel):
    """A representative PC per segment (lab, Batfish traceroutes, PT checklist pings)."""

    model_config = _CFG
    name: str
    site: str
    segment: str
    vlan: int
    ip: str
    prefix: int
    gateway: str
    switch: str
    port: str


class NetworkPlan(BaseModel):
    model_config = _CFG
    requirements: Requirements
    devices: list[Device] = Field(default_factory=list)
    cabling: list[Cable] = Field(default_factory=list)
    hosts: list[EndHost] = Field(default_factory=list)
    links: list[PlanLink] = Field(default_factory=list)
    segments: list[PlanSegment] = Field(default_factory=list)
    addressing: AddressingPlan | None = None
    routing: RoutingDesign = Field(default_factory=RoutingDesign)
    vpn_tunnels: list[VpnTunnel] = Field(default_factory=list)
    qos_policies: list[QosPolicy] = Field(default_factory=list)
    acl_policies: list[AclPolicy] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def sites(self) -> list[Site]:
        return self.requirements.sites

    def device(self, hostname: str) -> Device:
        return next(d for d in self.devices if d.hostname == hostname)
