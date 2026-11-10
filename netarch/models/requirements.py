"""Input schema (technical.md §4.1) and validation that reports every failure at once.

Field-level rules live on the pydantic models. Cross-field rules (site ids, VLAN uniqueness,
link endpoints, copper distance, address overlap, dual_homed) run in ``_cross_checks`` over
the raw input so they still report even when an unrelated field is broken.

CIDR parsing is pure integer math; ``ipaddress`` is only a test oracle (CLAUDE.md).
"""

from __future__ import annotations

import json
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError
from pydantic_core import PydanticCustomError

from netarch.errors import (
    AddressOverlapError,
    InputValidationError,
    NetArchError,
    PhysicalDistanceViolationError,
    TopologyConstraintError,
)

PRESET_NAMES: tuple[str, ...] = ("campus", "metro", "global")

COPPER_MAX_M = 100.0
DISTANCE_MAX_M = 120_000.0
ROOT_PREFIX_MIN, ROOT_PREFIX_MAX = 8, 30

# --- integer CIDR helpers --------------------------------------------------------------

_FULL = 0xFFFFFFFF


def _mask(prefix: int) -> int:
    return (_FULL << (32 - prefix)) & _FULL


def _plain_decimal(s: str) -> bool:
    return s.isascii() and s.isdigit() and not (len(s) > 1 and s[0] == "0")


def parse_ipv4(text: str) -> int:
    """Dotted quad → int. Rejects leading zeros, signs, spaces and out-of-range octets."""
    parts = text.split(".")
    if len(parts) != 4:
        raise ValueError(f"{text!r} is not a dotted-quad IPv4 address")
    value = 0
    for part in parts:
        if not _plain_decimal(part):
            raise ValueError(f"{text!r}: octet {part!r} is not a plain decimal number")
        octet = int(part)
        if octet > 255:
            raise ValueError(f"{text!r}: octet {octet} is above 255")
        value = (value << 8) | octet
    return value


def parse_cidr(text: str) -> tuple[int, int, bool]:
    """'a.b.c.d/p' → (address int, prefix, host_bits_set). Raises ValueError if malformed."""
    if not isinstance(text, str) or text.count("/") != 1:
        raise ValueError(f"{text!r} is not in a.b.c.d/prefix form")
    addr_s, prefix_s = text.split("/")
    if not _plain_decimal(prefix_s):
        raise ValueError(f"{text!r}: prefix {prefix_s!r} is not a plain decimal number")
    prefix = int(prefix_s)
    if prefix > 32:
        raise ValueError(f"{text!r}: prefix /{prefix} is above /32")
    addr = parse_ipv4(addr_s)
    return addr, prefix, (addr & ~_mask(prefix) & _FULL) != 0


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True if two (network, prefix) blocks share any address."""
    shorter = min(a[1], b[1])
    m = _mask(shorter)
    return (a[0] & m) == (b[0] & m)


def contains(outer: tuple[int, int], inner: tuple[int, int]) -> bool:
    return inner[1] >= outer[1] and (inner[0] & _mask(outer[1])) == outer[0]


RFC1918: tuple[tuple[str, tuple[int, int]], ...] = (
    ("10.0.0.0/8", (0x0A000000, 8)),
    ("172.16.0.0/12", (0xAC100000, 12)),
    ("192.168.0.0/16", (0xC0A80000, 16)),
)


def in_rfc1918(block: tuple[int, int]) -> bool:
    return any(contains(r, block) for _, r in RFC1918)


def _strict_cidr(text: str) -> tuple[int, int]:
    try:
        addr, prefix, host_bits = parse_cidr(text)
    except ValueError as exc:
        raise PydanticCustomError("cidr_invalid", "{reason}", {"reason": str(exc)}) from None
    if host_bits:
        net = addr & _mask(prefix)
        raise PydanticCustomError(
            "cidr_host_bits",
            "{text} has host bits set; the network address for /{prefix} is {net}",
            {"text": text, "prefix": prefix, "net": _dotted(net) + f"/{prefix}"},
        )
    return addr, prefix


def _dotted(x: int) -> str:
    return f"{x >> 24 & 255}.{x >> 16 & 255}.{x >> 8 & 255}.{x & 255}"


def _check_cidr(text: str) -> str:
    _strict_cidr(text)
    return text


def _check_root(text: str) -> str:
    _, prefix = _strict_cidr(text)
    if not ROOT_PREFIX_MIN <= prefix <= ROOT_PREFIX_MAX:
        raise PydanticCustomError(
            "root_prefix_range",
            "root prefix /{prefix} is outside /8–/30",
            {"prefix": prefix},
        )
    return text


def _check_vlan(v: int) -> int:
    if v == 1:
        raise PydanticCustomError(
            "vlan_default", "VLAN 1 is the default VLAN and is never used for data", {}
        )
    if v == 999:
        raise PydanticCustomError(
            "vlan_native",
            "VLAN 999 is reserved as the unused native VLAN on trunks (technical.md §6.2)",
            {},
        )
    if 1002 <= v <= 1005:
        raise PydanticCustomError(
            "vlan_reserved", "VLAN {v} is reserved (1002–1005, legacy FDDI/Token Ring)", {"v": v}
        )
    if not 2 <= v <= 4094:
        raise PydanticCustomError("vlan_range", "VLAN {v} is outside 2–4094", {"v": v})
    return v


def _check_two_decimals(d: float) -> float:
    if Decimal(repr(d)).as_tuple().exponent < -2:
        raise PydanticCustomError(
            "distance_decimals", "distance {d} m has more than 2 decimals", {"d": d}
        )
    return d


Cidr = Annotated[str, AfterValidator(_check_cidr)]
RootCidr = Annotated[str, AfterValidator(_check_root)]
Vlan = Annotated[int, Field(strict=True), AfterValidator(_check_vlan)]

# --- schema --------------------------------------------------------------------------

_STRICT = ConfigDict(extra="forbid")

SegmentRole = Literal["users", "wireless", "management", "servers", "labs", "iot", "trading"]
SiteKind = Literal["building", "hq", "remote", "colo", "city"]


class Segment(BaseModel):
    model_config = _STRICT
    name: str = Field(min_length=1)
    vlan: Vlan
    hosts: int = Field(strict=True, ge=1)
    growth_pct: float = Field(strict=True, ge=0, le=200)
    role: SegmentRole


class Site(BaseModel):
    model_config = _STRICT
    id: str = Field(min_length=1)
    kind: SiteKind
    segments: list[Segment] = Field(min_length=1)
    access_points: int = Field(default=0, strict=True, ge=0)
    access_run_max_m: float | None = Field(default=None, strict=True, gt=0)


class Link(BaseModel):
    model_config = _STRICT
    a: str = Field(min_length=1)
    b: str = Field(min_length=1)
    distance_m: Annotated[
        float, Field(strict=True, gt=0, le=DISTANCE_MAX_M), AfterValidator(_check_two_decimals)
    ]
    inter_building: bool = False
    required_gbps: float = Field(strict=True, gt=0)
    requested_media: Literal["copper", "om4", "os2"] | None = None


class AddressSpace(BaseModel):
    model_config = _STRICT
    root: RootCidr
    reserved: list[Cidr] = Field(default_factory=list)


class Cloud(BaseModel):
    model_config = _STRICT
    vpc_cidr: Cidr


class Requirements(BaseModel):
    model_config = _STRICT
    profile_name: str = Field(min_length=1)
    profile_type: Literal["campus", "metro", "global"]
    address_space: AddressSpace
    sites: list[Site] = Field(min_length=1)
    links: list[Link] = Field(default_factory=list)
    resiliency: Literal["dual_uplink", "dual_homed"]
    latency_target_ms: float | None = Field(default=None, strict=True, gt=0)
    cloud: Cloud | None = None
    target_dialect: Literal["pt", "full"] = "pt"


# --- error collection ------------------------------------------------------------------

_HINTS = {
    "cidr_invalid": "Write the network as a.b.c.d/prefix, e.g. 10.0.0.0/16.",
    "cidr_host_bits": "Use the network address (all host bits zero) for this prefix.",
    "root_prefix_range": "Pick a root between /8 and /30.",
    "vlan_default": "Use a VLAN between 2 and 4094 other than 1 and 1002–1005.",
    "vlan_native": "Use a VLAN between 2 and 4094 other than 1, 999 and 1002–1005.",
    "vlan_reserved": "Use a VLAN between 2 and 4094 other than 1 and 1002–1005.",
    "vlan_range": "Use a VLAN between 2 and 4094 other than 1 and 1002–1005.",
    "distance_decimals": "Give distances in metres with at most 2 decimals.",
    "extra_forbidden": "Remove the field or fix its spelling (see technical.md §4.1).",
    "missing": "Add the required field (see technical.md §4.1).",
}


def _field_path(loc: tuple[Any, ...]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out or "<root>"


def _from_pydantic(err: dict[str, Any]) -> InputValidationError:
    kind = err["type"]
    return InputValidationError(
        field=_field_path(err["loc"]),
        value=err.get("input"),
        rule_id=f"INPUT.{kind}",
        message=err["msg"],
        hint=_HINTS.get(kind, "Fix the value to match technical.md §4.1."),
    )


def _try(model: type[BaseModel], raw: Any) -> Any:
    try:
        return model.model_validate(raw)
    except ValidationError:
        return None


def _valid_block(text: Any, root: bool = False) -> tuple[int, int] | None:
    try:
        (_check_root if root else _check_cidr)(text)
    except (PydanticCustomError, TypeError, AttributeError):
        return None
    if not isinstance(text, str):
        return None
    addr, prefix, _ = parse_cidr(text)
    return addr, prefix


def _vlan_ok(v: Any) -> bool:
    if not isinstance(v, int) or isinstance(v, bool):
        return False
    try:
        _check_vlan(v)
    except PydanticCustomError:
        return False
    return True


def _site_checks(sites: list[Any]) -> tuple[list[NetArchError], list[str]]:
    errs: list[NetArchError] = []
    ids: list[str] = []
    for i, site in enumerate(sites):
        if not isinstance(site, dict):
            continue
        sid = site.get("id")
        if isinstance(sid, str) and sid:
            if sid in ids:
                errs.append(InputValidationError(
                    field=f"sites[{i}].id", value=sid, rule_id="INPUT.SITE_ID_DUPLICATE",
                    message=f"site id {sid!r} is used more than once",
                    hint="Give every site a unique id.",
                ))
            ids.append(sid)
        segs = site.get("segments")
        if not isinstance(segs, list):
            continue
        seen: set[int] = set()
        for j, seg in enumerate(segs):
            v = seg.get("vlan") if isinstance(seg, dict) else None
            if not _vlan_ok(v):
                continue
            if v in seen:
                errs.append(InputValidationError(
                    field=f"sites[{i}].segments[{j}].vlan", value=v,
                    rule_id="INPUT.VLAN_DUPLICATE",
                    message=f"VLAN {v} is used twice in site {sid!r}",
                    hint="Use a unique VLAN id for each segment within a site.",
                ))
            seen.add(v)
    return errs, ids


def _link_checks(links: list[Any], ids: list[str]) -> list[NetArchError]:
    errs: list[NetArchError] = []
    for i, link in enumerate(links):
        if not isinstance(link, dict):
            continue
        for end in ("a", "b"):
            v = link.get(end)
            if isinstance(v, str) and v and v not in ids:
                errs.append(InputValidationError(
                    field=f"links[{i}].{end}", value=v, rule_id="INPUT.LINK_ENDPOINT",
                    message=f"link endpoint {v!r} is not a defined site",
                    hint=f"Use one of the site ids: {', '.join(ids) or '(none)'}.",
                ))
        if isinstance(link.get("a"), str) and link.get("a") and link.get("a") == link.get("b"):
            errs.append(InputValidationError(
                field=f"links[{i}].b", value=link["b"], rule_id="INPUT.LINK_SELF",
                message=f"link connects site {link['b']!r} to itself",
                hint="A link must join two different sites.",
            ))
        ok = _try(Link, link)
        if ok and ok.requested_media == "copper" and ok.distance_m > COPPER_MAX_M:
            errs.append(PhysicalDistanceViolationError.for_link(
                ok.a, ok.b, ok.distance_m, field=f"links[{i}].requested_media"
            ))
    return errs


def _dual_homed_checks(sites: list[Any], links: list[Any]) -> list[NetArchError]:
    errs: list[NetArchError] = []
    ends = [
        (lk.get("a"), lk.get("b")) for lk in links
        if isinstance(lk, dict) and lk.get("a") != lk.get("b")
    ]
    for i, raw in enumerate(sites):
        site = _try(Site, raw)
        if site is None or site.kind != "remote":
            continue
        n = sum(1 for a, b in ends if site.id in (a, b))
        if n < 2:
            errs.append(TopologyConstraintError(
                field=f"sites[{i}]", value=site.id, rule_id="TOP.DUAL_HOMED",
                message=(f"resiliency is dual_homed but remote site {site.id!r} has {n} "
                         "link(s); it needs at least 2 (primary to HQ, backup to Colo)"),
                hint="Add a second link for this site or change resiliency to dual_uplink.",
            ))
    return errs


def _address_checks(data: dict[str, Any]) -> list[NetArchError]:
    errs: list[NetArchError] = []
    space = data.get("address_space")
    space = space if isinstance(space, dict) else {}
    root_text = space.get("root")
    root = _valid_block(root_text, root=True)
    reserved_raw = space.get("reserved")
    reserved: list[tuple[str, tuple[int, int]]] = []
    for i, text in enumerate(reserved_raw if isinstance(reserved_raw, list) else []):
        blk = _valid_block(text)
        if blk is None:
            continue
        field = f"address_space.reserved[{i}]"
        if not in_rfc1918(blk):
            errs.append(_rfc1918_error(field, text))
            continue
        clash = next((t for t, b in reserved if overlaps(b, blk)), None)
        if clash:
            errs.append(AddressOverlapError(
                field=field, value=text, rule_id="ADDR.OVERLAP",
                message=f"reserved range {text} overlaps reserved range {clash}",
                hint="Merge or separate the reserved ranges.",
            ))
            continue
        reserved.append((text, blk))

    cloud = data.get("cloud")
    vpc_text = cloud.get("vpc_cidr") if isinstance(cloud, dict) else None
    vpc = _valid_block(vpc_text)
    if vpc is not None:
        field = "cloud.vpc_cidr"
        if not in_rfc1918(vpc):
            errs.append(_rfc1918_error(field, vpc_text))
        elif root is not None and overlaps(root, vpc):
            errs.append(AddressOverlapError(
                field=field, value=vpc_text, rule_id="ADDR.OVERLAP",
                message=(f"cloud VPC {vpc_text} overlaps the root {root_text}, "
                         "which the plan allocates from"),
                hint="Choose a VPC CIDR outside the root, e.g. 172.31.0.0/16.",
            ))
        else:
            clash = next((t for t, b in reserved if overlaps(b, vpc)), None)
            if clash:
                errs.append(AddressOverlapError(
                    field=field, value=vpc_text, rule_id="ADDR.OVERLAP",
                    message=f"cloud VPC {vpc_text} overlaps reserved range {clash}",
                    hint="Choose a VPC CIDR that avoids the reserved ranges.",
                ))
    return errs


def _rfc1918_error(field: str, text: str) -> AddressOverlapError:
    return AddressOverlapError(
        field=field, value=text, rule_id="ADDR.RFC1918",
        message=f"{text} is not inside RFC 1918 private space "
                f"({', '.join(n for n, _ in RFC1918)})",
        hint="Use a range inside 10/8, 172.16/12 or 192.168/16.",
    )


def _cross_checks(data: dict[str, Any]) -> list[NetArchError]:
    sites = data.get("sites") if isinstance(data.get("sites"), list) else []
    links = data.get("links") if isinstance(data.get("links"), list) else []
    errs, ids = _site_checks(sites)
    errs += _link_checks(links, ids)
    if data.get("resiliency") == "dual_homed":
        errs += _dual_homed_checks(sites, links)
    errs += _address_checks(data)
    return errs


def collect_errors(data: Any) -> list[NetArchError]:
    """Every problem in ``data``, field-level and cross-field, as typed errors."""
    errs: list[NetArchError] = []
    try:
        Requirements.model_validate(data)
    except ValidationError as exc:
        errs += [_from_pydantic(e) for e in exc.errors()]
    if isinstance(data, dict):
        errs += _cross_checks(data)
    return errs


def load_requirements(data: Any) -> Requirements:
    """Validate and return the model. One problem raises its own typed error; several raise
    ``InputValidationError`` whose ``errors`` lists all of them."""
    errs = collect_errors(data)
    if len(errs) == 1:
        raise errs[0]
    if errs:
        raise InputValidationError.aggregate(errs)
    return Requirements.model_validate(data)


def load_requirements_file(path: str | Path) -> Requirements:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputValidationError(
            field="<file>", value=str(path), rule_id="INPUT.FILE",
            message=f"cannot read {path} as JSON: {exc}",
            hint="Check the path and that the file is valid JSON.",
        ) from None
    return load_requirements(data)


def load_preset(name: str) -> Requirements:
    if name not in PRESET_NAMES:
        raise InputValidationError(
            field="preset", value=name, rule_id="INPUT.PRESET",
            message=f"unknown preset {name!r}",
            hint=f"Choose one of: {', '.join(PRESET_NAMES)}.",
        )
    text = (files("netarch") / "presets" / f"{name}.json").read_text(encoding="utf-8")
    return load_requirements(json.loads(text))
