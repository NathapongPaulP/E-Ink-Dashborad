from fastapi import APIRouter, Depends
from app.schema import ProjectsCreate, ProjectsRead
from app.db import get_session
from app.models import Projects
from sqlmodel import select, Session

router = APIRouter(prefix="/api", tags=["api"])

@router.get("/projects", response_model=list[ProjectsRead])
def get_projects(session: Session = Depends(get_session)):
    return session.exec(
        select(Projects).where(Projects.archived_at.is_(None))
    ).all()


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
            deadline=item.deadline or None,
        )
        for item in data
    ]

    session.add_all(projects)
    session.commit()
    return projects
