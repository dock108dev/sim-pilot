#!/usr/bin/env python3
# pyright: reportPrivateUsage=false, reportAttributeAccessIssue=false
"""Profile the read-only OpenTTD world collection used by gameplay analysis."""

from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from time import perf_counter
from typing import Any

from sim_pilot.cli import _bridge_observation, _world_from_observation
from sim_pilot.openttd.gamescript.client import GameScriptBridgeClient
from sim_pilot.openttd.gamescript.messages import (
    BridgeMessage,
    MessageType,
    WorldCollectionPagePayload,
)
from sim_pilot.openttd.world_translation import infer_routes as original_infer_routes


async def profile_once() -> dict[str, Any]:
    started = perf_counter()
    category_seconds: defaultdict[str, float] = defaultdict(float)
    counts: defaultdict[str, int] = defaultdict(int)
    route_inference_seconds = 0.0
    original_receive = GameScriptBridgeClient._receive

    async def receive(
        self: GameScriptBridgeClient, *, allow_resync_baseline: bool = False
    ) -> BridgeMessage:
        receive_started = perf_counter()
        message = await original_receive(self, allow_resync_baseline=allow_resync_baseline)
        elapsed = perf_counter() - receive_started
        if message.message_type is MessageType.WORLD_COLLECTION_PAGE:
            payload = WorldCollectionPagePayload.model_validate(message.payload)
            category = payload.collection.value
            counts[category] += len(payload.items)
            category_seconds[category] += elapsed
        elif message.message_type in {
            MessageType.WORLD_MANIFEST,
            MessageType.WORLD_SNAPSHOT_COMPLETE,
        }:
            category_seconds["world_manifest"] += elapsed
        return message

    def infer_routes(*args: Any, **kwargs: Any) -> Any:
        nonlocal route_inference_seconds
        route_started = perf_counter()
        result = original_infer_routes(*args, **kwargs)
        route_inference_seconds += perf_counter() - route_started
        return result

    import sim_pilot.openttd.world_translation as translation

    GameScriptBridgeClient._receive = receive
    translation.infer_routes = infer_routes
    try:
        observation, health = await _bridge_observation()
        world = _world_from_observation(observation)
    finally:
        GameScriptBridgeClient._receive = original_receive
        translation.infer_routes = original_infer_routes
    total = perf_counter() - started
    categories: dict[str, dict[str, int | float]] = {
        category: {
            "entities": counts[category],
            "seconds": round(seconds, 6),
        }
        for category, seconds in sorted(category_seconds.items())
    }
    categories["inferred_routes"] = {
        "entities": len(world.routes),
        "seconds": round(route_inference_seconds, 6),
    }
    return {
        "total_seconds": round(total, 6),
        "world_id": world.metadata.world_id,
        "observer_company_id": world.metadata.observer_company_id,
        "save_generation": world.metadata.save_generation,
        "capability_fingerprint": world.metadata.capability_fingerprint,
        "bridge_sequence": health.last_sequence,
        "categories": categories,
    }


async def main() -> None:
    if (
        os.getenv("SIM_PILOT_OPENTTD_ALLOW_WRITES", "0") != "0"
        or os.getenv("SIM_PILOT_OPENTTD_GS_ALLOW_WRITES", "0") != "0"
    ):
        raise SystemExit("profiling requires both OpenTTD write flags to be 0")
    print(json.dumps({"runs": [await profile_once(), await profile_once()]}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
