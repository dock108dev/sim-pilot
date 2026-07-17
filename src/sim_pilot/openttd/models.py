"""Typed state exposed by OpenTTD 15.3 Admin Network protocol v3."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


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
        )


class OpenTTDAdapterCapabilities(OpenTTDModel):
    read_state: Literal[True] = True
    execute_actions: Literal[False] = False
    supports_restore: Literal[False] = False
    supports_reconciliation: Literal[False] = False
    supports_pause: Literal[False] = False
    supports_events: Literal[False] = False


class OpenTTDAdapterMetadata(OpenTTDModel):
    adapter_type: Literal["openttd"] = "openttd"
    integration_version: Literal["admin-network-v3"] = "admin-network-v3"
    capabilities: OpenTTDAdapterCapabilities = OpenTTDAdapterCapabilities()


class OpenTTDObservationState(OpenTTDModel):
    game: OpenTTDState
    resources: OpenTTDResourceMapping
    adapter: OpenTTDAdapterMetadata = OpenTTDAdapterMetadata()

    @classmethod
    def from_game_state(cls, state: OpenTTDState) -> OpenTTDObservationState:
        return cls(game=state, resources=OpenTTDResourceMapping.from_state(state))


class OpenTTDClient(Protocol):
    """Adapter-independent client contract used by production and test clients."""

    @property
    def metadata(self) -> OpenTTDConnectionMetadata: ...

    async def connect(self) -> None: ...

    async def collect_state(self) -> OpenTTDState: ...

    async def close(self) -> None: ...
