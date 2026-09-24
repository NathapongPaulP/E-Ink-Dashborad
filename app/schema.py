from datetime import date, datetime
from typing import Literal
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.models import Source

# The DB has CHECK (points in (1, 2, 3, 5, 8)). Repeating it here turns a bad
# value into a 422 with a useful message instead of a 500 from the constraint.
Points = Literal[1, 2, 3, 5, 8]


class ProjectsCreate(SQLModel):
    # Lengths mirror the columns in models.Projects so oversized input is
    # rejected as a 422 instead of blowing up as a Postgres DataError.
    name: str = Field(max_length=100)
    status: str = Field(default="", max_length=34)
    urgent: bool
    important: bool
    deadline: date | None = None


class ProjectsRead(SQLModel):
    id: UUID
    name: str
    status: str
    urgent: bool
    important: bool
    deadline: date | None
    created_at: datetime
    # Rolled up from the project's steps. progress is 0.0-1.0, which is what
    # the display's bar-drawing code multiplies by its pixel width.
    points_done: int = 0
    points_total: int = 0
    progress: float = 0.0
    # Title of the undone step with the lowest position: what to work on
    # next. None when the project has no steps or every step is done.
    current_step: str | None = None


class StepsCreate(SQLModel):
    title: str
    points: Points
    source: Source = Source.Manual
    # Omit to append to the end of the project's list.
    position: int | None = None


class StepsUpdate(SQLModel):
    """Every field optional: only what the request actually sends is applied."""

    title: str | None = None
    points: Points | None = None
    position: int | None = None
    # done is the writable face of done_at: true stamps it, false clears it.
    done: bool | None = None


class StepsRead(SQLModel):
    id: UUID
    project_id: UUID
    title: str
    points: int
    position: int
    source: Source
    done_at: datetime | None
    done: bool
