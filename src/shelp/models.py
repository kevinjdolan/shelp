from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DecisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["command", "message"]
    command: str
    message_instruction: str


class ConversationalReplyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str


@dataclass(frozen=True)
class ProviderSettings:
    provider: Literal["anthropic", "openai", "gemini"]
    model: str
    api_key: str


@dataclass(frozen=True)
class ChoiceOption:
    label: str
    value: str
    description: str = ""
