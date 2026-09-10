"""Editable initial workforce proposals. Never overrides existing Owner assignments."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import ROOT


class WorkforceSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models_data: list[tuple[str, None, str]] = Field(min_length=1, max_length=100)
    agents_def: list[tuple[str, str, str]] = Field(min_length=1, max_length=100)

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
