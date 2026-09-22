from fastapi import Depends, FastAPI
from sqlmodel import Session, select

from app.db import get_session
from app.models import Projects
from app.schema import ProjectsCreate, ProjectsRead

app = FastAPI()


@app.get("/api/projects", response_model=list[ProjectsRead])
def get_projects(session: Session = Depends(get_session)):
    return session.exec(
        select(Projects).where(Projects.archived_at.is_(None))
    ).all()


@app.post("/api/projects", response_model=list[ProjectsRead], status_code=201)
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
    return projects
