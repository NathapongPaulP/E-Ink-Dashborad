from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, func
from sqlmodel import Field, SQLModel

# Timestamps are stored in UTC; calendar days (snapshot_date, verdict_date) are
# the dashboard's local days. Always cross between the two with to_local_date(),
# never by comparing a UTC timestamp's .date() to a local date.
APP_TZ = ZoneInfo("Asia/Bangkok")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today_local() -> date:
    return datetime.now(APP_TZ).date()


def to_local_date(moment: datetime) -> date:
    """The local calendar day a stored (UTC) timestamp falls on."""
    return moment.astimezone(APP_TZ).date()


class Source(str, Enum):
    AI = "AI"
    Manual = "Manual"


class Projects(SQLModel, table=True):
    __tablename__ = "projects"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=100)
    status: str = Field(max_length=34, default="")
    urgent: bool = False
    important: bool = False
    deadline: date | None = None
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )
    archived_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class Steps(SQLModel, table=True):
    __tablename__ = "steps"
    __table_args__ = (
        CheckConstraint("points in (1, 2, 3, 5, 8)", name="valid_points"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    project_id: UUID = Field(foreign_key="projects.id", ondelete="CASCADE", index=True)
    title: str
    points: int
    position: int
    source: Source = Source.Manual
    done_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))

    @property
    def done(self) -> bool:
        """done_at doubles as the completion flag; this is the readable face of
        it. Not a column - schema.StepsRead picks it up by attribute name."""
        return self.done_at is not None


class DailySnapshots(SQLModel, table=True):
    __tablename__ = "daily_snapshots"

    project_id: UUID = Field(
        foreign_key="projects.id", ondelete="CASCADE", primary_key=True
    )
    snapshot_date: date = Field(default_factory=today_local, primary_key=True)
    points_done: int
    points_total: int
    percent: float = 0


class Verdicts(SQLModel, table=True):
    __tablename__ = "verdicts"

    project_id: UUID = Field(
        foreign_key="projects.id", ondelete="CASCADE", primary_key=True
    )
    verdict_date: date = Field(default_factory=today_local, primary_key=True)
    message: str
