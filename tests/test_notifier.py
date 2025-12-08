from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Notification
from src.services.notifier import Notifier, NotifierConfig


def test_notifier_persists_and_returns_row():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    with Session() as session:
        notifier = Notifier(session, NotifierConfig(enabled=False))
        row = notifier.notify(title="test", message="hello world", level="warn")
        stored = session.get(Notification, row.id)

    assert stored is not None
    assert stored.level == "warn"
    assert stored.title == "test"
