from typing import Literal

from pydantic import BaseModel, Field


class PlanEdit(BaseModel):
    code: str
    title: str = Field(min_length=1, max_length=200)
    points: Literal[1, 2, 3, 5, 8]
    depends_on: list[str] = Field(max_length=40)
    expected_revision: int


class ExperienceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    lesson: str = Field(min_length=1, max_length=3000)


class ExperienceDecision(BaseModel):
    decision: Literal["publish", "reject"]
