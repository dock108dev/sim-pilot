"""Candidate Task 7B bridge envelope used by Task 7A probes."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_GS_TO_ADMIN_BYTES = 1450
MAX_ADMIN_TO_GS_BYTES = 8999


class MessageType(StrEnum):
    HELLO = "hello"
    CAPABILITIES = "capabilities"
    STATE_SNAPSHOT = "state_snapshot"
    EVENT = "event"
    COMMAND_REQUEST = "command_request"
    COMMAND_COMPLETED = "command_completed"
    COMMAND_REJECTED = "command_rejected"
    HEARTBEAT = "heartbeat"
    SAVE = "save"
    LOAD = "load"
    ERROR = "error"


class BridgeCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    protocol_version: Literal[1] = 1
    read_resources: tuple[str, ...] = ()
    write_actions: tuple[str, ...] = ()
    company_contexts: tuple[str, ...] = ()
    cost_estimation: bool = False
    command_deduplication: bool = False


class BridgeEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    protocol_version: Literal[1] = 1
    sequence: int = Field(ge=1)
    message_id: str = Field(min_length=1, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)
    script_instance_id: str = Field(min_length=1, max_length=128)
    message_type: MessageType
    game_date: int = Field(ge=0)
    company_id: int | None = Field(default=None, ge=0, le=14)
    payload: dict[str, object]

    @model_validator(mode="after")
    def validate_correlation(self) -> Self:
        if (
            self.message_type
            in {
                MessageType.COMMAND_COMPLETED,
                MessageType.COMMAND_REJECTED,
            }
            and self.correlation_id is None
        ):
            raise ValueError("command response requires correlation_id")
        return self

    def to_json(self, *, outbound_limit: int = MAX_GS_TO_ADMIN_BYTES) -> str:
        encoded = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        if len(encoded.encode()) > outbound_limit:
            raise ValueError(f"bridge message exceeds {outbound_limit} bytes")
        return encoded

    @classmethod
    def from_json(cls, value: str, *, inbound_limit: int = MAX_ADMIN_TO_GS_BYTES) -> Self:
        if len(value.encode()) > inbound_limit:
            raise ValueError(f"bridge message exceeds {inbound_limit} bytes")
        return cls.model_validate_json(value, strict=True)


class DuplicateTracker:
    """Bounded in-process proof of message-ID duplicate classification."""

    def __init__(self, capacity: int = 256) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._ids: list[str] = []

    def accept(self, message_id: str) -> bool:
        if message_id in self._ids:
            return False
        self._ids.append(message_id)
        if len(self._ids) > self.capacity:
            self._ids.pop(0)
        return True
