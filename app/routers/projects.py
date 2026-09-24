from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from app.db import get_session
from app.models import Projects, Steps
from app.schema import ProjectsCreate, ProjectsRead

router = APIRouter(prefix="/api", tags=["projects"])


def _to_read(
    project: Projects, done: int, total: int, current_step: str | None = None
) -> ProjectsRead:
    return ProjectsRead(
        **project.model_dump(),
        points_done=done,
        points_total=total,
        # A project with no steps is 0%, not a crash and not 100%.
        progress=round(done / total, 4) if total else 0.0,
        current_step=current_step,
    )


@router.get("/projects", response_model=list[ProjectsRead])
def get_projects(session: Session = Depends(get_session)):
    # Rolled up in one grouped query rather than per project: the display asks
    # for the whole board every 15 minutes, and N+1 would scale with the board.
    points_done = func.coalesce(
        func.sum(case((Steps.done_at.is_not(None), Steps.points), else_=0)), 0
    )
    points_total = func.coalesce(func.sum(Steps.points), 0)

    # The next step to work on: undone, lowest position. It runs on an alias
    # because the outer query already joins Steps for the sums, and the
    # subquery must look at this project's steps, not at the joined row.
    # Positions aren't unique, so id breaks ties to keep the pick stable.
    next_step = aliased(Steps)
    current_step = (
        select(next_step.title)
        .where(next_step.project_id == Projects.id, next_step.done_at.is_(None))
        .order_by(next_step.position, next_step.id)
        .limit(1)
        .correlate(Projects)
        .scalar_subquery()
    )

    rows = session.exec(
        select(Projects, points_done, points_total, current_step)
        # outerjoin, so a project with no steps still appears (as 0%).
        .outerjoin(Steps, Steps.project_id == Projects.id)
        .where(Projects.archived_at.is_(None))
        .group_by(Projects.id)
        .order_by(Projects.created_at)
    ).all()

    return [_to_read(*row) for row in rows]


@router.post("/projects", response_model=list[ProjectsRead], status_code=201)
def create_projects(
    data: list[ProjectsCreate], session: Session = Depends(get_session)
):
    projects = [
        Projects(
            name=item.name,
            status=item.status,
            urgent=item.urgent,
            important=item.important,
            deadline=item.deadline,
        )
        for item in data
    ]

    session.add_all(projects)
    session.commit()
    # Freshly created projects have no steps yet, so the rollup is known: 0/0.
    return [_to_read(p, 0, 0) for p in projects]
