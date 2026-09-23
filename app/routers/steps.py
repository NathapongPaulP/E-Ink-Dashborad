from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.models import Projects, Steps, utcnow
from app.schema import StepsCreate, StepsRead, StepsUpdate

router = APIRouter(prefix="/api", tags=["steps"])


def _require_project(session: Session, project_id: UUID) -> Projects:
    """Without this the FK violation surfaces as a 500. 404 is the honest answer."""
    project = session.get(Projects, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _require_step(session: Session, step_id: UUID) -> Steps:
    step = session.get(Steps, step_id)
    if step is None:
        raise HTTPException(status_code=404, detail="step not found")
    return step


@router.get("/projects/{project_id}/steps", response_model=list[StepsRead])
def list_steps(project_id: UUID, session: Session = Depends(get_session)):
    _require_project(session, project_id)
    return session.exec(
        select(Steps).where(Steps.project_id == project_id).order_by(Steps.position)
    ).all()


@router.post(
    "/projects/{project_id}/steps", response_model=list[StepsRead], status_code=201
)
def create_steps(
    project_id: UUID,
    data: list[StepsCreate],
    session: Session = Depends(get_session),
):
    _require_project(session, project_id)

    # One query for the current tail, then hand out consecutive slots. Asking
    # the DB per step would race with itself inside a single request.
    next_position = (
        session.exec(
            select(func.coalesce(func.max(Steps.position), -1)).where(
                Steps.project_id == project_id
            )
        ).one()
        + 1
    )

    steps = []
    for item in data:
        if item.position is None:
            position = next_position
            next_position += 1
        else:
            position = item.position
        steps.append(
            Steps(
                project_id=project_id,
                title=item.title,
                points=item.points,
                position=position,
                source=item.source,
            )
        )

    session.add_all(steps)
    session.commit()
    return steps


@router.patch("/steps/{step_id}", response_model=StepsRead)
def update_step(
    step_id: UUID, data: StepsUpdate, session: Session = Depends(get_session)
):
    step = _require_step(session, step_id)

    # exclude_unset distinguishes "field omitted" from "field set to null":
    # PATCH {"done": false} must clear done_at, PATCH {"title": "x"} must not.
    changes = data.model_dump(exclude_unset=True)

    if "done" in changes:
        done = changes.pop("done")
        # Re-completing an already-done step keeps the original timestamp.
        if done and step.done_at is None:
            step.done_at = utcnow()
        elif not done:
            step.done_at = None

    for field, value in changes.items():
        setattr(step, field, value)

    session.add(step)
    session.commit()
    return step


@router.delete("/steps/{step_id}", status_code=204)
def delete_step(step_id: UUID, session: Session = Depends(get_session)):
    session.delete(_require_step(session, step_id))
    session.commit()
