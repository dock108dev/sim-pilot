"""Async client for observed state and narrow RCON on OpenTTD 15.3 Admin Network v3."""

from __future__ import annotations

import asyncio
import logging
import struct
from collections.abc import Callable
from typing import TypeVar

from sim_pilot.openttd.config import OpenTTDConfiguration
from sim_pilot.openttd.errors import (
    OpenTTDConnectionRefusedError,
    OpenTTDDisconnectedError,
    OpenTTDInvalidResponseError,
    OpenTTDProtocolMismatchError,
    OpenTTDStateUnavailableError,
    OpenTTDTimeoutError,
    OpenTTDUnsupportedVersionError,
)
from sim_pilot.openttd.models import (
    OpenTTDCompanyState,
    OpenTTDConnectionMetadata,
    OpenTTDMapMetadata,
    OpenTTDState,
    OpenTTDStationFacilityCounts,
    OpenTTDVehicleCounts,
)
from sim_pilot.openttd.protocol import (
    MAX_PACKET_SIZE,
    AdminUpdateFrequency,
    AdminUpdateType,
    CompanyEconomy,
    CompanyInfo,
    CompanyStats,
    DecodedPacket,
    PacketType,
    ProtocolDescription,
    RconResponse,
    Welcome,
    decode_packet,
    encode_gamescript,
    encode_join,
    encode_packet,
    encode_poll,
    encode_rcon,
    encode_update_frequency,
    format_game_date,
)

T = TypeVar("T")
logger = logging.getLogger(__name__)


class OpenTTDAdminClient:
    """Collect the supported observation snapshot without mutating OpenTTD."""

    def __init__(self, configuration: OpenTTDConfiguration) -> None:
        self.configuration = configuration
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._metadata: OpenTTDConnectionMetadata | None = None
        self._map: OpenTTDMapMetadata | None = None
        self._protocol: ProtocolDescription | None = None

    @property
    def metadata(self) -> OpenTTDConnectionMetadata:
        if self._metadata is None:
            raise OpenTTDDisconnectedError("OpenTTD client is not connected")
        return self._metadata

    async def connect(self) -> None:
        if self._writer is not None:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.configuration.host, self.configuration.port),
                timeout=self.configuration.connection_timeout_seconds,
            )
        except TimeoutError as error:
            raise OpenTTDTimeoutError("timed out connecting to OpenTTD admin port") from error
        except (ConnectionRefusedError, OSError) as error:
            raise OpenTTDConnectionRefusedError(
                f"cannot connect to OpenTTD at {self.configuration.host}:{self.configuration.port}"
            ) from error

        try:
            await self._send(
                encode_join(self.configuration.password.get_secret_value()),
                self.configuration.connection_timeout_seconds,
            )
            protocol = await self._receive_payload(
                PacketType.SERVER_PROTOCOL,
                ProtocolDescription,
                self.configuration.connection_timeout_seconds,
            )
            if protocol.version != self.configuration.expected_protocol:
                raise OpenTTDProtocolMismatchError(
                    f"expected admin protocol {self.configuration.expected_protocol}, "
                    f"received {protocol.version}"
                )
            required_poll_types = {
                AdminUpdateType.DATE,
                AdminUpdateType.COMPANY_INFO,
                AdminUpdateType.COMPANY_ECONOMY,
                AdminUpdateType.COMPANY_STATS,
            }
            unsupported = sorted(
                update_type.name
                for update_type in required_poll_types
                if protocol.update_frequencies.get(update_type, 0) & 1 == 0
            )
            if unsupported:
                raise OpenTTDProtocolMismatchError(
                    "admin protocol does not advertise polling for: " + ", ".join(unsupported)
                )
            self._protocol = protocol
            welcome = await self._receive_payload(
                PacketType.SERVER_WELCOME,
                Welcome,
                self.configuration.connection_timeout_seconds,
            )
            if not _version_matches(welcome.openttd_version, self.configuration.expected_version):
                raise OpenTTDUnsupportedVersionError(
                    f"expected OpenTTD {self.configuration.expected_version}, "
                    f"received {welcome.openttd_version}"
                )
            self._metadata = OpenTTDConnectionMetadata(
                protocol_version=protocol.version,
                openttd_version=welcome.openttd_version,
                server_name=welcome.server_name,
                dedicated=welcome.dedicated,
            )
            self._map = OpenTTDMapMetadata(
                generation_seed=welcome.generation_seed,
                landscape=welcome.landscape,
                calendar_start_date_raw=welcome.calendar_start_date_raw,
                width=welcome.map_width,
                height=welcome.map_height,
            )
        except Exception:
            await self.close()
            raise

    async def collect_state(self) -> OpenTTDState:
        self._require_connected()
        company_id = self.configuration.company_id
        timeout = self.configuration.observation_timeout_seconds
        await self._send(encode_poll(AdminUpdateType.COMPANY_INFO, company_id), timeout)
        try:
            info = await self._receive_matching(
                PacketType.SERVER_COMPANY_INFO,
                CompanyInfo,
                lambda value: value.company_id == company_id,
                timeout,
            )
        except OpenTTDTimeoutError as error:
            raise OpenTTDStateUnavailableError(
                f"company {company_id} is not available from the OpenTTD admin port"
            ) from error

        await self._send(encode_poll(AdminUpdateType.DATE), timeout)
        game_date_raw = await self._receive_payload(PacketType.SERVER_DATE, int, timeout)
        await self._send(encode_poll(AdminUpdateType.COMPANY_ECONOMY), timeout)
        economy = await self._receive_matching(
            PacketType.SERVER_COMPANY_ECONOMY,
            CompanyEconomy,
            lambda value: value.company_id == company_id,
            timeout,
        )
        await self._send(encode_poll(AdminUpdateType.COMPANY_STATS), timeout)
        stats = await self._receive_matching(
            PacketType.SERVER_COMPANY_STATS,
            CompanyStats,
            lambda value: value.company_id == company_id,
            timeout,
        )
        if self._map is None:
            raise OpenTTDInvalidResponseError("welcome metadata is unavailable")
        return OpenTTDState(
            connection=self.metadata,
            map=self._map,
            game_date_raw=game_date_raw,
            game_date=format_game_date(game_date_raw),
            company=_company_state(info, economy, stats),
        )

    async def execute_rcon(self, command: str) -> tuple[str, ...]:
        """Execute one bounded Admin Network rcon command and await its matching end marker."""
        timeout = self.configuration.action_timeout_seconds
        await self._send(encode_rcon(command), timeout)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        output: list[str] = []
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise OpenTTDTimeoutError("timed out waiting for OpenTTD rcon completion")
            packet = await self._read_packet(remaining)
            if packet.type == PacketType.SERVER_RCON:
                if not isinstance(packet.payload, RconResponse):
                    raise OpenTTDInvalidResponseError("invalid OpenTTD rcon response")
                output.append(packet.payload.message)
            elif packet.type == PacketType.SERVER_RCON_END:
                if packet.payload != command:
                    raise OpenTTDInvalidResponseError("OpenTTD rcon completion command mismatch")
                return tuple(output)

    async def subscribe_gamescript(self) -> None:
        """Subscribe the single Admin connection to official GameScript broadcasts."""
        self._require_connected()
        protocol = self._protocol
        if protocol is None:
            raise OpenTTDInvalidResponseError("admin protocol description is unavailable")
        supported = protocol.update_frequencies.get(AdminUpdateType.GAMESCRIPT, 0)
        if supported & AdminUpdateFrequency.AUTOMATIC == 0:
            raise OpenTTDProtocolMismatchError(
                "admin protocol does not advertise automatic GameScript updates"
            )
        await self._send(
            encode_update_frequency(AdminUpdateType.GAMESCRIPT, AdminUpdateFrequency.AUTOMATIC),
            self.configuration.connection_timeout_seconds,
        )

    async def send_gamescript(self, value: str) -> None:
        await self._send(encode_gamescript(value), self.configuration.observation_timeout_seconds)

    async def receive_gamescript(self, timeout: float | None = None) -> str:
        deadline = asyncio.get_running_loop().time() + (
            timeout or self.configuration.observation_timeout_seconds
        )
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise OpenTTDTimeoutError("timed out waiting for a GameScript bridge message")
            packet = await self._read_packet(remaining)
            if packet.type != PacketType.SERVER_GAMESCRIPT:
                continue
            if not isinstance(packet.payload, str):
                raise OpenTTDInvalidResponseError("invalid GameScript packet payload")
            return packet.payload

    async def reconnect(self) -> None:
        await self.close()
        await self.connect()

    async def close(self) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        self._metadata = None
        self._map = None
        self._protocol = None
        if writer is None:
            return
        try:
            writer.write(encode_packet(PacketType.ADMIN_QUIT))
            await writer.drain()
        except (ConnectionError, OSError) as error:
            logger.warning(
                "OpenTTD close handshake failed stage=admin_quit error_type=%s",
                type(error).__name__,
            )
        try:
            writer.close()
            await writer.wait_closed()
        except (ConnectionError, OSError) as error:
            logger.warning(
                "OpenTTD socket close failed stage=wait_closed error_type=%s",
                type(error).__name__,
            )

    async def _send(self, data: bytes, timeout: float) -> None:
        self._require_connected()
        writer = self._writer
        if writer is None:
            raise OpenTTDDisconnectedError("OpenTTD client is not connected")
        try:
            writer.write(data)
            await asyncio.wait_for(writer.drain(), timeout=timeout)
        except TimeoutError as error:
            raise OpenTTDTimeoutError("timed out writing to OpenTTD") from error
        except (ConnectionError, OSError) as error:
            raise OpenTTDDisconnectedError("OpenTTD disconnected while writing") from error

    async def _read_packet(self, timeout: float) -> DecodedPacket:
        self._require_connected()
        reader = self._reader
        if reader is None:
            raise OpenTTDDisconnectedError("OpenTTD client is not connected")
        try:
            size_data = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
            size = struct.unpack("<H", size_data)[0]
            if size < 3 or size > MAX_PACKET_SIZE:
                raise OpenTTDInvalidResponseError(f"invalid protocol packet size: {size}")
            body = await asyncio.wait_for(reader.readexactly(size - 2), timeout=timeout)
        except TimeoutError as error:
            raise OpenTTDTimeoutError("timed out waiting for OpenTTD state") from error
        except asyncio.IncompleteReadError as error:
            raise OpenTTDDisconnectedError("OpenTTD disconnected during a packet") from error
        packet = decode_packet(body[0], body[1:])
        if packet.type == PacketType.SERVER_ERROR:
            raise OpenTTDInvalidResponseError(f"OpenTTD admin error code {packet.payload}")
        if packet.type in (PacketType.SERVER_FULL, PacketType.SERVER_BANNED):
            raise OpenTTDConnectionRefusedError("OpenTTD rejected the admin connection")
        if packet.type == PacketType.SERVER_SHUTDOWN:
            raise OpenTTDDisconnectedError("OpenTTD server is shutting down")
        return packet

    async def _receive_payload(
        self,
        packet_type: PacketType,
        payload_type: type[T],
        timeout: float,
    ) -> T:
        return await self._receive_matching(packet_type, payload_type, lambda _: True, timeout)

    async def _receive_matching(
        self,
        packet_type: PacketType,
        payload_type: type[T],
        predicate: Callable[[T], bool],
        timeout: float,
    ) -> T:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise OpenTTDTimeoutError(f"timed out waiting for packet {packet_type.name}")
            packet = await self._read_packet(remaining)
            if packet.type != packet_type:
                continue
            if not isinstance(packet.payload, payload_type):
                raise OpenTTDInvalidResponseError(
                    f"packet {packet_type.name} has an invalid payload"
                )
            value = packet.payload
            if predicate(value):
                return value

    def _require_connected(self) -> None:
        if self._reader is None or self._writer is None:
            raise OpenTTDDisconnectedError("OpenTTD client is not connected")


def _version_matches(actual: str, expected: str) -> bool:
    return actual == expected or actual.startswith(f"{expected}-")


def _company_state(
    info: CompanyInfo,
    economy: CompanyEconomy,
    stats: CompanyStats,
) -> OpenTTDCompanyState:
    if len({info.company_id, economy.company_id, stats.company_id}) != 1:
        raise OpenTTDInvalidResponseError("company snapshot combines different company IDs")
    return OpenTTDCompanyState(
        company_id=info.company_id,
        name=info.name,
        manager_name=info.manager_name,
        colour=info.colour,
        inaugurated_year=info.inaugurated_year,
        is_ai=info.is_ai,
        quarters_of_bankruptcy=info.quarters_of_bankruptcy,
        cash=economy.cash,
        loan=economy.loan,
        net_income_current_year=economy.net_income_current_year,
        delivered_cargo_current_quarter=economy.delivered_cargo_current_quarter,
        company_value_last_quarter=economy.company_value_last_quarter,
        performance_last_quarter=economy.performance_last_quarter,
        delivered_cargo_last_quarter=economy.delivered_cargo_last_quarter,
        company_value_previous_quarter=economy.company_value_previous_quarter,
        performance_previous_quarter=economy.performance_previous_quarter,
        delivered_cargo_previous_quarter=economy.delivered_cargo_previous_quarter,
        vehicles=OpenTTDVehicleCounts(
            trains=stats.vehicle_counts[0],
            lorries=stats.vehicle_counts[1],
            buses=stats.vehicle_counts[2],
            aircraft=stats.vehicle_counts[3],
            ships=stats.vehicle_counts[4],
        ),
        station_facilities=OpenTTDStationFacilityCounts(
            train_stations=stats.station_counts[0],
            lorry_stations=stats.station_counts[1],
            bus_stops=stats.station_counts[2],
            airports=stats.station_counts[3],
            harbours=stats.station_counts[4],
        ),
    )
