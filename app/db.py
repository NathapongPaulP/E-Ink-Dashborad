import os

from dotenv import load_dotenv
from sqlmodel import Session, create_engine

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])


def get_session():
    # expire_on_commit=False keeps instances readable after commit, so routes
    # can serialize what they just wrote without re-querying each row.
    with Session(engine, expire_on_commit=False) as session:
        yield session
