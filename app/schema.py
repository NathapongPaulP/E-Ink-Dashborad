from datetime import date, datetime
from uuid import UUID

from sqlmodel import Field, SQLModel


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
