"""
Vendor-aware RADIUS reply attributes.

A package means the same thing on every router (time, idle timeout, speed,
data cap, an optional router-side profile), but each manufacturer reads it
from different attributes. Vendors that share a convention share an
attribute *family* (Ubiquiti, TP-Link Omada, Cambium, Ruijie and pfSense all
honour WISPr bandwidth attributes, for example).

Relay writes the families for the vendors present in the fleet into the
package's radgroupreply rows. A NAS ignores attributes from other vendors,
so one group serves a mixed fleet. FreeRADIUS must have each family's
dictionary loaded (stock FreeRADIUS ships all of these); that is why only
requested families are written rather than all of them.

Units: rates arrive in kbit/s, data caps in bytes. Each family converts to
what its vendor expects. Attributes marked "verify" in the notes should be
confirmed on a lab unit of that vendor's current firmware.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

Attribute = tuple[str, str]

GIGAWORD = 2**32


@dataclass(frozen=True)
class PackagePolicy:
    session_timeout_seconds: int | None = None
    idle_timeout_seconds: int | None = None
    interim_interval_seconds: int | None = None
    upload_kbps: int | None = None
    download_kbps: int | None = None
    data_limit_bytes: int | None = None
    profile: str | None = None


def _common(policy: PackagePolicy) -> list[Attribute]:
    attributes: list[Attribute] = []
    if policy.session_timeout_seconds:
        attributes.append(("Session-Timeout", str(policy.session_timeout_seconds)))
    if policy.idle_timeout_seconds:
        attributes.append(("Idle-Timeout", str(policy.idle_timeout_seconds)))
    if policy.interim_interval_seconds:
        attributes.append(("Acct-Interim-Interval", str(policy.interim_interval_seconds)))
    return attributes


def _mikrotik(policy: PackagePolicy) -> list[Attribute]:
    attributes: list[Attribute] = []
    if policy.upload_kbps and policy.download_kbps:
        # RouterOS reads rx/tx from the router's side: rx = client upload.
        attributes.append(("Mikrotik-Rate-Limit", f"{policy.upload_kbps}k/{policy.download_kbps}k"))
    if policy.data_limit_bytes:
        attributes.append(("Mikrotik-Total-Limit", str(policy.data_limit_bytes % GIGAWORD)))
        if policy.data_limit_bytes >= GIGAWORD:
            attributes.append(("Mikrotik-Total-Limit-Gigawords", str(policy.data_limit_bytes // GIGAWORD)))
    if policy.profile:
        attributes.append(("Mikrotik-Group", policy.profile))
    return attributes


def _huawei(policy: PackagePolicy) -> list[Attribute]:
    attributes: list[Attribute] = []
    if policy.upload_kbps and policy.download_kbps:
        # bit/s; "input" is traffic coming in from the user (upload).
        attributes.append(("Huawei-Input-Average-Rate", str(policy.upload_kbps * 1000)))
        attributes.append(("Huawei-Output-Average-Rate", str(policy.download_kbps * 1000)))
    if policy.data_limit_bytes:
        # kbytes remaining (verify per firmware).
        attributes.append(("Huawei-Remanent-Volume", str(policy.data_limit_bytes // 1024)))
    if policy.profile:
        attributes.append(("Filter-Id", policy.profile))
    return attributes


def _wispr(policy: PackagePolicy) -> list[Attribute]:
    attributes: list[Attribute] = []
    if policy.upload_kbps and policy.download_kbps:
        attributes.append(("WISPr-Bandwidth-Max-Up", str(policy.upload_kbps * 1000)))
        attributes.append(("WISPr-Bandwidth-Max-Down", str(policy.download_kbps * 1000)))
    return attributes


def _chillispot(policy: PackagePolicy) -> list[Attribute]:
    attributes: list[Attribute] = []
    if policy.upload_kbps and policy.download_kbps:
        attributes.append(("ChilliSpot-Bandwidth-Max-Up", str(policy.upload_kbps)))
        attributes.append(("ChilliSpot-Bandwidth-Max-Down", str(policy.download_kbps)))
    if policy.data_limit_bytes:
        attributes.append(("ChilliSpot-Max-Total-Octets", str(policy.data_limit_bytes % GIGAWORD)))
        if policy.data_limit_bytes >= GIGAWORD:
            attributes.append(("ChilliSpot-Max-Total-Gigawords", str(policy.data_limit_bytes // GIGAWORD)))
    return attributes


def _aruba(policy: PackagePolicy) -> list[Attribute]:
    # Aruba applies bandwidth contracts through the user role on the controller.
    return [("Aruba-User-Role", policy.profile)] if policy.profile else []


def _cisco(policy: PackagePolicy) -> list[Attribute]:
    # Cisco applies a named ACL/QoS policy configured on the device.
    return [("Filter-Id", policy.profile)] if policy.profile else []


def _nokia(policy: PackagePolicy) -> list[Attribute]:
    # Nokia BNG / WLAN-GW selects an SLA profile that carries the rates.
    return [("Alc-SLA-Prof-Str", policy.profile)] if policy.profile else []


@dataclass(frozen=True)
class AttributeFamily:
    key: str
    build: Callable[[PackagePolicy], list[Attribute]]
    managed: tuple[str, ...]
    supports_rate: bool
    supports_quota: bool
    supports_profile: bool


FAMILIES: dict[str, AttributeFamily] = {
    "mikrotik": AttributeFamily("mikrotik", _mikrotik, ("Mikrotik-Rate-Limit", "Mikrotik-Total-Limit", "Mikrotik-Total-Limit-Gigawords", "Mikrotik-Group"), True, True, True),
    "huawei": AttributeFamily("huawei", _huawei, ("Huawei-Input-Average-Rate", "Huawei-Output-Average-Rate", "Huawei-Remanent-Volume", "Filter-Id"), True, True, True),
    "wispr": AttributeFamily("wispr", _wispr, ("WISPr-Bandwidth-Max-Up", "WISPr-Bandwidth-Max-Down"), True, False, False),
    "chillispot": AttributeFamily("chillispot", _chillispot, ("ChilliSpot-Bandwidth-Max-Up", "ChilliSpot-Bandwidth-Max-Down", "ChilliSpot-Max-Total-Octets", "ChilliSpot-Max-Total-Gigawords"), True, True, False),
    "aruba": AttributeFamily("aruba", _aruba, ("Aruba-User-Role",), False, False, True),
    "cisco": AttributeFamily("cisco", _cisco, ("Filter-Id",), False, False, True),
    "nokia": AttributeFamily("nokia", _nokia, ("Alc-SLA-Prof-Str",), False, False, True),
}

COMMON_ATTRIBUTES = ("Session-Timeout", "Idle-Timeout", "Acct-Interim-Interval")


@dataclass(frozen=True)
class Vendor:
    key: str
    label: str
    family: str | None
    nas_type: str
    notes: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)


# Keys match LumaNet's RouterVendor enum values.
VENDORS: dict[str, Vendor] = {
    vendor.key: vendor
    for vendor in (
        Vendor("mikrotik", "MikroTik RouterOS", "mikrotik", "mikrotik"),
        Vendor("huawei", "Huawei", "huawei", "other", "Average-rate and remaining-volume VSAs (vendor 2011); verify volume units per firmware."),
        Vendor("tplink_omada", "TP-Link Omada", "wispr", "other", "WISPr bandwidth via the Omada controller's external RADIUS."),
        Vendor("ubiquiti", "Ubiquiti UniFi", "wispr", "other"),
        Vendor("cambium", "Cambium", "wispr", "other"),
        Vendor("ruijie", "Ruijie", "wispr", "other"),
        Vendor("pfsense", "pfSense / OPNsense", "wispr", "other", "Captive portal honours WISPr bandwidth attributes."),
        Vendor("openwrt", "OpenWrt / CoovaChilli", "chillispot", "other"),
        Vendor("aruba", "Aruba", "aruba", "other", "Rates come from the user role configured on the controller."),
        Vendor("cisco", "Cisco", "cisco", "cisco", "Filter-Id names an ACL or policy configured on the device."),
        Vendor("nokia", "Nokia", "nokia", "other", "SLA profile name; rates live in the BNG's SLA profile."),
        Vendor("other", "Other", None, "other", "Only standard attributes (session/idle timeout, interim interval)."),
    )
}

MANAGED_ATTRIBUTES: tuple[str, ...] = tuple(
    dict.fromkeys([*COMMON_ATTRIBUTES, *(name for family in FAMILIES.values() for name in family.managed)])
)


def families_for(vendors: list[str] | None) -> list[str]:
    """Attribute families to write for these vendor keys; MikroTik when none are given."""
    keys = vendors or ["mikrotik"]
    unknown = [key for key in keys if key not in VENDORS]
    if unknown:
        raise ValueError(f"Unknown vendor(s): {', '.join(sorted(unknown))}")
    return list(dict.fromkeys(family for key in keys if (family := VENDORS[key].family)))


def build_reply_attributes(policy: PackagePolicy, vendors: list[str] | None = None) -> list[Attribute]:
    """All reply attributes for this package across the given vendors, without duplicates."""
    attributes = _common(policy)
    for family in families_for(vendors):
        attributes.extend(FAMILIES[family].build(policy))
    return list(dict.fromkeys(attributes))


def parse_rate_limit(rate_limit: str) -> tuple[int, int] | None:
    """Legacy "10M/20M" (upload/download) → (upload_kbps, download_kbps)."""
    try:
        up, down = rate_limit.lower().split("/")
    except ValueError:
        return None

    def to_kbps(value: str) -> int:
        value = value.strip()
        if value.endswith("m"):
            return int(float(value[:-1]) * 1000)
        if value.endswith("k"):
            return int(float(value[:-1]))
        return int(float(value) / 1000)

    try:
        return to_kbps(up), to_kbps(down)
    except ValueError:
        return None


def nas_type_for(value: str | None) -> str | None:
    """A NAS `type` given as a vendor key becomes FreeRADIUS's NAS type string."""
    if value is None:
        return None
    return VENDORS[value].nas_type if value in VENDORS else value
