"""Binary Admin Network codec tests against the OpenTTD 15.3 layout."""

import struct

import pytest

from sim_pilot.openttd.errors import OpenTTDInvalidResponseError
from sim_pilot.openttd.protocol import (
    AdminUpdateType,
    CompanyEconomy,
    PacketType,
    decode_packet,
    encode_join,
    encode_poll,
    encode_rcon,
    format_game_date,
)


def test_join_and_poll_use_little_endian_size_prefixed_packets() -> None:
    join = encode_join("secret")
    poll = encode_poll(AdminUpdateType.COMPANY_INFO, 3)

    assert struct.unpack("<H", join[:2])[0] == len(join)
    assert join[2] == PacketType.ADMIN_JOIN
    assert join[3:] == b"secret\x00sim-pilot\x006b\x00"
    assert poll == struct.pack("<HBBI", 8, PacketType.ADMIN_POLL, 2, 3)
    assert encode_rcon('server_name "Sim Pilot"') == (
        struct.pack("<HB", 27, PacketType.ADMIN_RCON) + b'server_name "Sim Pilot"\x00'
    )


def test_economy_money_bit_patterns_are_signed() -> None:
    payload = b"".join(
        (
            struct.pack("<B", 0),
            struct.pack("<q", -25_000),
            struct.pack("<Q", 300_000),
            struct.pack("<q", -75_000),
            struct.pack("<H", 10),
            struct.pack("<qHH", 150_000, 300, 20),
            struct.pack("<qHH", 175_000, 320, 25),
        )
    )

    decoded = decode_packet(PacketType.SERVER_COMPANY_ECONOMY, payload)

    assert isinstance(decoded.payload, CompanyEconomy)
    assert decoded.payload.cash == -25_000
    assert decoded.payload.net_income_current_year == -75_000


@pytest.mark.parametrize(
    ("raw", "formatted"),
    [(0, "0-01-01"), (59, "0-02-29"), (366, "1-01-01"), (712223, "1950-01-01")],
)
def test_game_date_conversion_matches_openttd_calendar(raw: int, formatted: str) -> None:
    assert format_game_date(raw) == formatted


def test_malformed_packet_string_is_rejected() -> None:
    with pytest.raises(OpenTTDInvalidResponseError, match="unterminated"):
        decode_packet(PacketType.SERVER_WELCOME, b"missing terminator")
