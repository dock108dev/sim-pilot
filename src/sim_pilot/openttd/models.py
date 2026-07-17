"""Typed state exposed by OpenTTD 15.3 Admin Network protocol v3."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.openttd.gamescript.models import BridgeHealth


class OpenTTDModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1


class OpenTTDConnectionMetadata(OpenTTDModel):
    integration_method: Literal["admin_network"] = "admin_network"
    protocol_version: int = Field(ge=1)
    openttd_version: str = Field(min_length=1)
    server_name: str = Field(min_length=1)
    dedicated: bool
    connected: bool = True


class OpenTTDMapMetadata(OpenTTDModel):
    generation_seed: int = Field(ge=0)
    landscape: int = Field(ge=0, le=3)
    calendar_start_date_raw: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class OpenTTDVehicleCounts(OpenTTDModel):
    trains: int = Field(ge=0)
    lorries: int = Field(ge=0)
    buses: int = Field(ge=0)
    aircraft: int = Field(ge=0)
    ships: int = Field(ge=0)

    @property
    def total(self) -> int:
        return self.trains + self.lorries + self.buses + self.aircraft + self.ships


class OpenTTDStationFacilityCounts(OpenTTDModel):
    train_stations: int = Field(ge=0)
    lorry_stations: int = Field(ge=0)
    bus_stops: int = Field(ge=0)
    airports: int = Field(ge=0)
    harbours: int = Field(ge=0)

    @property
    def total(self) -> int:
        return (
            self.train_stations
            + self.lorry_stations
            + self.bus_stops
            + self.airports
            + self.harbours
        )


class OpenTTDCompanyState(OpenTTDModel):
    company_id: int = Field(ge=0, le=14)
    name: str = Field(min_length=1)
    manager_name: str = Field(min_length=1)
    colour: int = Field(ge=0, le=255)
    inaugurated_year: int = Field(ge=0)
    is_ai: bool
    quarters_of_bankruptcy: int = Field(ge=0)
    cash: int
    loan: int = Field(ge=0)
    net_income_current_year: int
    delivered_cargo_current_quarter: int = Field(ge=0)
    company_value_last_quarter: int
    performance_last_quarter: int = Field(ge=0)
    delivered_cargo_last_quarter: int = Field(ge=0)
    company_value_previous_quarter: int
    performance_previous_quarter: int = Field(ge=0)
    delivered_cargo_previous_quarter: int = Field(ge=0)
    vehicles: OpenTTDVehicleCounts
    station_facilities: OpenTTDStationFacilityCounts


class OpenTTDState(OpenTTDModel):
    connection: OpenTTDConnectionMetadata
    map: OpenTTDMapMetadata
    game_date_raw: int = Field(ge=0)
    game_date: str = Field(pattern=r"^\d+-\d{2}-\d{2}$")
    company: OpenTTDCompanyState


class OpenTTDResourceMapping(OpenTTDModel):
    cash: int
    debt: int = Field(ge=0)
    company_value: int
    income: None = None
    expenses: None = None
    profit: int
    vehicle_count: int = Field(ge=0)
    station_count: int = Field(ge=0)
    date: str
    date_raw: int = Field(ge=0)
    server_name: str = Field(min_length=1)
    paused: bool | None = None
    town_count: int | None = Field(default=None, ge=0)
    industry_count: int | None = Field(default=None, ge=0)
    company_name: str | None = Field(default=None, min_length=1)

    @classmethod
    def from_state(cls, state: OpenTTDState) -> OpenTTDResourceMapping:
        company = state.company
        return cls(
            cash=company.cash,
            debt=company.loan,
            company_value=company.company_value_last_quarter,
            profit=company.net_income_current_year,
            vehicle_count=company.vehicles.total,
            station_count=company.station_facilities.total,
            date=state.game_date,
            date_raw=state.game_date_raw,
            server_name=state.connection.server_name,
            company_name=company.name,
        )


class OpenTTDSourceAttribution(OpenTTDModel):
    admin_network_fields: tuple[str, ...]
    gamescript_fields: tuple[str, ...] = ()
    inconsistencies: tuple[str, ...] = ()


class OpenTTDAdapterCapabilities(OpenTTDModel):
    read_state: Literal[True] = True
    execute_actions: bool = False
    supports_restore: Literal[False] = False
    supports_reconciliation: bool = False
    supports_pause: Literal[False] = False
    supports_events: Literal[False] = False
    supports_set_server_name: bool = False
    bridge_detected: bool = False
    supports_full_snapshots: bool = False
    supports_state_deltas: Literal[False] = False
    supports_set_company_name: bool = False
    bridge_read_resources: tuple[str, ...] = ()
    bridge_actions: tuple[str, ...] = ()


class OpenTTDAdapterMetadata(OpenTTDModel):
    adapter_type: Literal["openttd"] = "openttd"
    integration_version: Literal["admin-network-v3", "admin-network-v3+gamescript-v1"] = (
        "admin-network-v3"
    )
    capabilities: OpenTTDAdapterCapabilities = OpenTTDAdapterCapabilities()


class OpenTTDObservationState(OpenTTDModel):
    tick: int = Field(ge=0)
    game: OpenTTDState
    resources: OpenTTDResourceMapping
    adapter: OpenTTDAdapterMetadata = OpenTTDAdapterMetadata()
    bridge: BridgeHealth | None = None
    source_attribution: OpenTTDSourceAttribution = OpenTTDSourceAttribution(
        admin_network_fields=(
            "connection",
            "map",
            "game_date",
            "company_identity",
            "company_economy",
            "aggregate_counts",
        )
    )

    @classmethod
    def from_game_state(cls, state: OpenTTDState) -> OpenTTDObservationState:
        return cls(
            tick=state.game_date_raw,
            game=state,
            resources=OpenTTDResourceMapping.from_state(state),
        )

    @classmethod
    def from_combined_state(
        cls,
        state: OpenTTDState,
        bridge: BridgeHealth,
        capabilities: OpenTTDAdapterCapabilities,
    ) -> OpenTTDObservationState:
        snapshot = bridge.snapshot
        if snapshot is None:
            raise ValueError("combined OpenTTD state requires a bridge snapshot")
        resources = OpenTTDResourceMapping.from_state(state).model_copy(
            update={
                "paused": snapshot.paused,
                "town_count": snapshot.town_count,
                "industry_count": snapshot.industry_count,
            }
        )
        inconsistencies: list[str] = []
        company = snapshot.company
        if company is None:
            inconsistencies.append("GameScript selected company is unavailable")
        else:
            comparisons = {
                "company_id": (state.company.company_id, company.company_id),
                "company_name": (state.company.name, company.name),
                "cash": (state.company.cash, company.cash),
                "loan": (state.company.loan, company.loan),
                "vehicle_count": (state.company.vehicles.total, company.vehicle_count),
                "station_count": (
                    state.company.station_facilities.total,
                    company.station_count,
                ),
            }
            inconsistencies.extend(
                f"{name}: admin={admin!r}, gamescript={script!r}"
                for name, (admin, script) in comparisons.items()
                if admin != script
            )
        return cls(
            tick=state.game_date_raw,
            game=state,
            resources=resources,
            adapter=OpenTTDAdapterMetadata(
                integration_version="admin-network-v3+gamescript-v1",
                capabilities=capabilities,
            ),
            bridge=bridge,
            source_attribution=OpenTTDSourceAttribution(
                admin_network_fields=(
                    "connection",
                    "map",
                    "game_date",
                    "company_identity",
                    "company_economy",
                    "aggregate_counts",
                ),
                gamescript_fields=(
                    "paused",
                    "town_count",
                    "industry_count",
                    "bridge_health",
                ),
                inconsistencies=tuple(inconsistencies),
            ),
        )


class OpenTTDClient(Protocol):
    """Adapter-independent client contract used by production and test clients."""

    @property
    def metadata(self) -> OpenTTDConnectionMetadata: ...

    async def connect(self) -> None: ...

    async def collect_state(self) -> OpenTTDState: ...

    async def execute_rcon(self, command: str) -> tuple[str, ...]: ...

    async def reconnect(self) -> None: ...

    async def close(self) -> None: ...
