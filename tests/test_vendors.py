import pytest

from app.vendors import GIGAWORD, MANAGED_ATTRIBUTES, VENDORS, PackagePolicy, build_reply_attributes, families_for, nas_type_for, parse_rate_limit

DAILY = PackagePolicy(session_timeout_seconds=86400, interim_interval_seconds=300, upload_kbps=2000, download_kbps=10000, data_limit_bytes=5 * GIGAWORD + 7)


def attrs(policy: PackagePolicy, vendors: list[str] | None) -> dict[str, str]:
    return dict(build_reply_attributes(policy, vendors))


def test_mikrotik_is_the_default_and_matches_routeros_conventions() -> None:
    result = attrs(DAILY, None)

    assert result["Session-Timeout"] == "86400"
    assert result["Acct-Interim-Interval"] == "300"
    assert result["Mikrotik-Rate-Limit"] == "2000k/10000k"
    assert result["Mikrotik-Total-Limit"] == "7"
    assert result["Mikrotik-Total-Limit-Gigawords"] == "5"
    assert not any(name.startswith(("Huawei", "WISPr")) for name in result)


def test_huawei_rates_are_bits_per_second_with_upload_as_input() -> None:
    result = attrs(DAILY, ["huawei"])

    assert result["Huawei-Input-Average-Rate"] == "2000000"
    assert result["Huawei-Output-Average-Rate"] == "10000000"
    assert "Mikrotik-Rate-Limit" not in result


@pytest.mark.parametrize("vendor", ["tplink_omada", "ubiquiti", "cambium", "ruijie", "pfsense"])
def test_wispr_vendors_get_bandwidth_in_bits_per_second(vendor: str) -> None:
    result = attrs(DAILY, [vendor])

    assert result["WISPr-Bandwidth-Max-Up"] == "2000000"
    assert result["WISPr-Bandwidth-Max-Down"] == "10000000"


def test_chillispot_gets_kbps_and_octet_quota() -> None:
    result = attrs(DAILY, ["openwrt"])

    assert result["ChilliSpot-Bandwidth-Max-Down"] == "10000"
    assert result["ChilliSpot-Max-Total-Gigawords"] == "5"


def test_profile_based_vendors_only_get_the_profile_name() -> None:
    policy = PackagePolicy(session_timeout_seconds=3600, upload_kbps=1000, download_kbps=1000, profile="free-tier")

    assert attrs(policy, ["aruba"]) == {"Session-Timeout": "3600", "Aruba-User-Role": "free-tier"}
    assert attrs(policy, ["nokia"])["Alc-SLA-Prof-Str"] == "free-tier"
    assert attrs(policy, ["cisco"])["Filter-Id"] == "free-tier"


def test_a_mixed_fleet_gets_every_family_once() -> None:
    result = build_reply_attributes(DAILY, ["mikrotik", "ubiquiti", "tplink_omada", "huawei"])
    names = [name for name, _ in result]

    assert len(names) == len(set(names))
    assert {"Mikrotik-Rate-Limit", "WISPr-Bandwidth-Max-Up", "Huawei-Input-Average-Rate"} <= set(names)
    assert families_for(["ubiquiti", "tplink_omada"]) == ["wispr"]


def test_other_vendors_only_get_standard_attributes() -> None:
    assert set(attrs(DAILY, ["other"])) == {"Session-Timeout", "Acct-Interim-Interval"}


def test_unknown_vendors_are_rejected() -> None:
    with pytest.raises(ValueError, match="juniper"):
        families_for(["juniper"])


def test_every_attribute_any_family_writes_is_managed() -> None:
    every_vendor = list(VENDORS)
    for name, _ in build_reply_attributes(PackagePolicy(3600, 60, 300, 1000, 2000, 10 * GIGAWORD, "p"), every_vendor):
        assert name in MANAGED_ATTRIBUTES


@pytest.mark.parametrize(("value", "expected"), [("10M/20M", (10000, 20000)), ("512k/2M", (512, 2000)), ("bad", None)])
def test_legacy_rate_limits_are_parsed(value: str, expected: tuple[int, int] | None) -> None:
    assert parse_rate_limit(value) == expected


def test_vendor_keys_map_to_freeradius_nas_types() -> None:
    assert nas_type_for("mikrotik") == "mikrotik"
    assert nas_type_for("huawei") == "other"
    assert nas_type_for("cisco") == "cisco"
    assert nas_type_for("custom") == "custom"
