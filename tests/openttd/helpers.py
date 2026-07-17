"""Deterministic OpenTTD state and protocol helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from sim_pilot.openttd.models import (
    OpenTTDCompanyState,
    OpenTTDConnectionMetadata,
    OpenTTDMapMetadata,
    OpenTTDState,
    OpenTTDStationFacilityCounts,
    OpenTTDVehicleCounts,
)
from sim_pilot.openttd.protocol import format_game_date

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "openttd" / "admin_snapshots.json"


def fixtures() -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", json.loads(FIXTURE_PATH.read_text()))


def fixture(name: str) -> dict[str, object]:
    return next(item for item in fixtures() if item["scenario"] == name)


def state(name: str = "profitable_company") -> OpenTTDState:
    item = fixture(name)
    vehicles = cast("list[int]", item["vehicles"])
    stations = cast("list[int]", item["stations"])
    game_date_raw = cast("int", item["game_date_raw"])
    return OpenTTDState(
        connection=OpenTTDConnectionMetadata(
            protocol_version=3,
            openttd_version="15.3",
            server_name="Fixture Server",
            dedicated=True,
        ),
        map=OpenTTDMapMetadata(
            generation_seed=12345,
            landscape=0,
            calendar_start_date_raw=712223,
            width=256,
            height=256,
        ),
        game_date_raw=game_date_raw,
        game_date=format_game_date(game_date_raw),
        company=OpenTTDCompanyState(
            company_id=0,
            name="Fixture Transport",
            manager_name="Ada Lovelace",
            colour=1,
            inaugurated_year=1950,
            is_ai=False,
            quarters_of_bankruptcy=0,
            cash=cast("int", item["cash"]),
            loan=cast("int", item["loan"]),
            net_income_current_year=cast("int", item["net_income_current_year"]),
            delivered_cargo_current_quarter=120,
            company_value_last_quarter=cast("int", item["company_value_last_quarter"]),
            performance_last_quarter=650,
            delivered_cargo_last_quarter=450,
            company_value_previous_quarter=700000,
            performance_previous_quarter=610,
            delivered_cargo_previous_quarter=420,
            vehicles=OpenTTDVehicleCounts(
                trains=vehicles[0],
                lorries=vehicles[1],
                buses=vehicles[2],
                aircraft=vehicles[3],
                ships=vehicles[4],
            ),
            station_facilities=OpenTTDStationFacilityCounts(
                train_stations=stations[0],
                lorry_stations=stations[1],
                bus_stops=stations[2],
                airports=stations[3],
                harbours=stations[4],
            ),
        ),
    )


class FakeOpenTTDClient:
    def __init__(self, states: list[OpenTTDState] | None = None) -> None:
        self.states = states or [state()]
        self.connected = False
        self.closed = False
        self.collect_calls = 0
        self.rcon_commands: list[str] = []
        self.reconnect_calls = 0

    @property
    def metadata(self) -> OpenTTDConnectionMetadata:
        return self.states[0].connection

    async def connect(self) -> None:
        self.connected = True

    async def collect_state(self) -> OpenTTDState:
        value = self.states[min(self.collect_calls, len(self.states) - 1)]
        self.collect_calls += 1
        return value

    async def execute_rcon(self, command: str) -> tuple[str, ...]:
        self.rcon_commands.append(command)
        prefix = 'server_name "'
        if not command.startswith(prefix) or not command.endswith('"'):
            return ("Unknown command",)
        name = command[len(prefix) : -1]
        self.states = [
            item.model_copy(
                update={"connection": item.connection.model_copy(update={"server_name": name})}
            )
            for item in self.states
        ]
        return (f"server_name = {name}",)

    async def reconnect(self) -> None:
        self.reconnect_calls += 1
        self.connected = True

    async def close(self) -> None:
        self.closed = True
        self.connected = False
