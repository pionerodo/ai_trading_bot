from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from src.core.config_loader import load_config


config = load_config()
db_cfg = config.get("database", {})

USER = db_cfg.get("user", "ai_trader")
PASSWORD = db_cfg.get("password", "")
HOST = db_cfg.get("host", "127.0.0.1")
PORT = db_cfg.get("port", 3306)
NAME = db_cfg.get("name", "ai_trading_bot")

DATABASE_URL = (
    f"mysql+pymysql://{USER}:{PASSWORD}@{HOST}:{PORT}/{NAME}?charset=utf8mb4"
)

engine = create_engine(
    DATABASE_URL,
    echo=bool(db_cfg.get("echo", False)),
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
