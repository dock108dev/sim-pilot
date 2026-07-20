"""Narrow codec for the OpenTTD 15.3 Admin Network protocol v3."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

from sim_pilot.openttd.errors import OpenTTDInvalidResponseError

MAX_PACKET_SIZE = 1460
ALL_COMPANIES = 0xFFFFFFFF


class PacketType(IntEnum):
    ADMIN_JOIN = 0
    ADMIN_QUIT = 1
    ADMIN_UPDATE_FREQUENCY = 2
    ADMIN_POLL = 3
    ADMIN_RCON = 5
    ADMIN_GAMESCRIPT = 6
    SERVER_FULL = 100
    SERVER_BANNED = 101
    SERVER_ERROR = 102
    SERVER_PROTOCOL = 103
    SERVER_WELCOME = 104
    SERVER_NEWGAME = 105
    SERVER_SHUTDOWN = 106
    SERVER_DATE = 107
    SERVER_COMPANY_NEW = 113
    SERVER_COMPANY_INFO = 114
    SERVER_COMPANY_UPDATE = 115
    SERVER_COMPANY_REMOVE = 116
    SERVER_COMPANY_ECONOMY = 117
    SERVER_COMPANY_STATS = 118
    SERVER_RCON = 120
    SERVER_GAMESCRIPT = 124
    SERVER_RCON_END = 125


class AdminUpdateType(IntEnum):
    DATE = 0
    CLIENT_INFO = 1
    COMPANY_INFO = 2
    COMPANY_ECONOMY = 3
    COMPANY_STATS = 4
    GAMESCRIPT = 9


class AdminUpdateFrequency(IntEnum):
    POLL = 1 << 0
    AUTOMATIC = 1 << 6


@dataclass(frozen=True)
class ProtocolDescription:
    version: int
    update_frequencies: dict[int, int]


@dataclass(frozen=True)
class Welcome:
    server_name: str
    openttd_version: str
    dedicated: bool
    map_name: str
    generation_seed: int
    landscape: int
    calendar_start_date_raw: int
    map_width: int
    map_height: int


@dataclass(frozen=True)
class CompanyInfo:
    company_id: int
    name: str
    manager_name: str
    colour: int
    protected: bool
    inaugurated_year: int
    is_ai: bool
    quarters_of_bankruptcy: int


@dataclass(frozen=True)
class CompanyEconomy:
    company_id: int
    cash: int
    loan: int
    net_income_current_year: int
    delivered_cargo_current_quarter: int
    company_value_last_quarter: int
    performance_last_quarter: int
    delivered_cargo_last_quarter: int
    company_value_previous_quarter: int
    performance_previous_quarter: int
    delivered_cargo_previous_quarter: int


@dataclass(frozen=True)
class CompanyStats:
    company_id: int
    vehicle_counts: tuple[int, int, int, int, int]
    station_counts: tuple[int, int, int, int, int]


@dataclass(frozen=True)
class RconResponse:
    colour: int
    message: str


@dataclass(frozen=True)
class DecodedPacket:
    type: int
    payload: object


class PacketReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def _take(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise OpenTTDInvalidResponseError("truncated OpenTTD Admin Network packet")
        value = self.data[self.offset : end]
        self.offset = end
        return value

    def u8(self) -> int:
        return self._take(1)[0]

    def boolean(self) -> bool:
        value = self.u8()
        if value not in (0, 1):
            raise OpenTTDInvalidResponseError("invalid protocol boolean")
        return value == 1

    def u16(self) -> int:
        return struct.unpack("<H", self._take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self._take(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self._take(8))[0]

    def i64_from_u64(self) -> int:
        """Interpret OpenTTD's serialized Money bit pattern as signed."""
        return struct.unpack("<q", self._take(8))[0]

    def string(self) -> str:
        end = self.data.find(b"\x00", self.offset)
        if end < 0:
            raise OpenTTDInvalidResponseError("unterminated protocol string")
        raw = self.data[self.offset : end]
        self.offset = end + 1
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise OpenTTDInvalidResponseError("invalid UTF-8 protocol string") from error


def _string(value: str) -> bytes:
    if "\x00" in value:
        raise ValueError("protocol strings cannot contain NUL")
    return value.encode("utf-8") + b"\x00"


def encode_packet(packet_type: int, payload: bytes = b"") -> bytes:
    body = bytes([packet_type]) + payload
    size = len(body) + 2
    if size > MAX_PACKET_SIZE:
        raise ValueError("OpenTTD Admin Network packet is too large")
    return struct.pack("<H", size) + body


def encode_join(password: str, name: str = "sim-pilot", version: str = "6b") -> bytes:
    return encode_packet(
        PacketType.ADMIN_JOIN, _string(password) + _string(name) + _string(version)
    )


def encode_poll(update_type: AdminUpdateType, identifier: int = ALL_COMPANIES) -> bytes:
    return encode_packet(PacketType.ADMIN_POLL, struct.pack("<BI", update_type, identifier))


def encode_rcon(command: str) -> bytes:
    return encode_packet(PacketType.ADMIN_RCON, _string(command))


def encode_update_frequency(update_type: AdminUpdateType, frequency: AdminUpdateFrequency) -> bytes:
    return encode_packet(
        PacketType.ADMIN_UPDATE_FREQUENCY,
        struct.pack("<HH", update_type, frequency),
    )


def encode_gamescript(value: str) -> bytes:
    return encode_packet(PacketType.ADMIN_GAMESCRIPT, _string(value))


def decode_packet(packet_type: int, data: bytes) -> DecodedPacket:
    reader = PacketReader(data)
    if packet_type == PacketType.SERVER_PROTOCOL:
        version = reader.u8()
        frequencies: dict[int, int] = {}
        while reader.boolean():
            update_type = reader.u16()
            frequencies[update_type] = reader.u16()
        payload: object = ProtocolDescription(version, frequencies)
    elif packet_type == PacketType.SERVER_WELCOME:
        payload = Welcome(
            server_name=reader.string(),
            openttd_version=reader.string(),
            dedicated=reader.boolean(),
            map_name=reader.string(),
            generation_seed=reader.u32(),
            landscape=reader.u8(),
            calendar_start_date_raw=reader.u32(),
            map_width=reader.u16(),
            map_height=reader.u16(),
        )
    elif packet_type == PacketType.SERVER_DATE:
        payload = reader.u32()
    elif packet_type == PacketType.SERVER_COMPANY_INFO:
        payload = CompanyInfo(
            company_id=reader.u8(),
            name=reader.string(),
            manager_name=reader.string(),
            colour=reader.u8(),
            protected=reader.boolean(),
            inaugurated_year=reader.u32(),
            is_ai=reader.boolean(),
            quarters_of_bankruptcy=reader.u8(),
        )
    elif packet_type == PacketType.SERVER_COMPANY_ECONOMY:
        payload = CompanyEconomy(
            company_id=reader.u8(),
            cash=reader.i64_from_u64(),
            loan=reader.u64(),
            net_income_current_year=reader.i64_from_u64(),
            delivered_cargo_current_quarter=reader.u16(),
            company_value_last_quarter=reader.i64_from_u64(),
            performance_last_quarter=reader.u16(),
            delivered_cargo_last_quarter=reader.u16(),
            company_value_previous_quarter=reader.i64_from_u64(),
            performance_previous_quarter=reader.u16(),
            delivered_cargo_previous_quarter=reader.u16(),
        )
    elif packet_type == PacketType.SERVER_COMPANY_STATS:
        company_id = reader.u8()
        payload = CompanyStats(
            company_id=company_id,
            vehicle_counts=_read_five_counts(reader),
            station_counts=_read_five_counts(reader),
        )
    elif packet_type == PacketType.SERVER_RCON:
        payload = RconResponse(colour=reader.u16(), message=reader.string())
    elif packet_type in (PacketType.SERVER_RCON_END, PacketType.SERVER_GAMESCRIPT):
        payload = reader.string()
    elif packet_type == PacketType.SERVER_ERROR:
        payload = reader.u8()
    else:
        payload = data
    return DecodedPacket(packet_type, payload)


def _read_five_counts(reader: PacketReader) -> tuple[int, int, int, int, int]:
    """Read the protocol's fixed rail, road, water, air, and total count tuple."""
    return (reader.u16(), reader.u16(), reader.u16(), reader.u16(), reader.u16())


def format_game_date(date_raw: int) -> str:
    """Match OpenTTD's proleptic Gregorian day-zero conversion."""
    if date_raw < 0:
        raise ValueError("OpenTTD date must be non-negative")
    days_per_400_years = 365 * 400 + 97
    year = 400 * (date_raw // days_per_400_years)
    remaining = date_raw % days_per_400_years
    first_century = 365 * 100 + 25
    later_century = 365 * 100 + 24
    if remaining >= first_century:
        year += 100
        remaining -= first_century
        centuries = remaining // later_century
        year += 100 * centuries
        remaining %= later_century
    if not _is_leap_year(year) and remaining >= 365 * 4:
        year += 4
        remaining -= 365 * 4
    four_year_blocks = remaining // (365 * 4 + 1)
    year += 4 * four_year_blocks
    remaining %= 365 * 4 + 1
    while remaining >= (366 if _is_leap_year(year) else 365):
        remaining -= 366 if _is_leap_year(year) else 365
        year += 1
    month_lengths = [31, 29 if _is_leap_year(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    month = 1
    for length in month_lengths:
        if remaining < length:
            return f"{year}-{month:02d}-{remaining + 1:02d}"
        remaining -= length
        month += 1
    raise AssertionError("unreachable OpenTTD date conversion")


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
