"""Editable initial workforce proposals. Never overrides existing Owner assignments."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import ROOT


class LlmAllocation(BaseModel):
    """Which models a role's employee thinks with, and what to do with more than one.

    Editable configuration, not architecture. The names here are resolved against the model
    registry the studio discovered; a name that matches nothing is reported and skipped, never
    invented. Nothing in the studio's logic reads these names — they only end up in the
    agent's slots, which the Owner can change from Settings at any time.
    """

    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1, max_length=50)
    primary: str = Field(min_length=1, max_length=200)
    secondary: str | None = Field(default=None, max_length=200)
    tertiary: str | None = Field(default=None, max_length=200)
    strategy: str = Field(default="SINGLE", max_length=20)
    policy: str = Field(default="IMPORTANT_ONLY", max_length=20)
    min_importance: str = Field(default="STRATEGIC", max_length=20)
    note: str = Field(default="", max_length=300)


class WorkforceSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models_data: list[tuple[str, None, str]] = Field(min_length=1, max_length=100)
    agents_def: list[tuple[str, str, str]] = Field(min_length=1, max_length=100)
    #: The starting allocation of models to roles. Applied only to an employee whose slots
    #: nobody has configured, so an Owner's own choice is never overwritten.
    llm_allocation: list[LlmAllocation] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def consistent(self) -> "WorkforceSeed":
        models = [row[0] for row in self.models_data]
        if len(set(models)) != len(models):
            raise ValueError("Duplicate seed model names")
        names = [row[0] for row in self.agents_def]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate seed agent names")
        if any(row[2] not in models for row in self.agents_def):
            raise ValueError("Initial agent refers to an undefined model proposal")
        if any(
            not value.strip() or len(value) > 200
            for rows in (self.models_data, self.agents_def)
            for row in rows
            for value in row
            if isinstance(value, str)
        ):
            raise ValueError("Invalid seed label")
        return self


def load_seed_config(path: Path | None = None) -> dict:
    source = path or ROOT / "config/workforce_seed.json"
    return WorkforceSeed.model_validate(json.loads(source.read_text(encoding="utf-8"))).model_dump()
