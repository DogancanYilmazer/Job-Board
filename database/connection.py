import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from pymongo import ASCENDING, DESCENDING, MongoClient


BASE_DIR = Path(__file__).resolve().parents[1]


def load_env_file() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()


class Settings:
    POSTGRES_DSN = os.getenv(
        "POSTGRES_DSN",
        "postgresql://postgres:postgres@localhost:5432/job_board_db",
    )
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB = os.getenv("MONGO_DB", "job_board_mongo")
    API_PREFIX = os.getenv("API_PREFIX", "/api/v1")


settings = Settings()


class Database:
    def __init__(self) -> None:
        self.pg_pool: Optional[SimpleConnectionPool] = None
        self.mongo_client: Optional[MongoClient] = None
        self.mongo_db = None

    def connect(self) -> None:
        if self.pg_pool is None:
            self.pg_pool = SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=settings.POSTGRES_DSN,
            )
        if self.mongo_client is None:
            self.mongo_client = MongoClient(settings.MONGO_URI)
            self.mongo_db = self.mongo_client[settings.MONGO_DB]

    def close(self) -> None:
        if self.pg_pool is not None:
            self.pg_pool.closeall()
            self.pg_pool = None
        if self.mongo_client is not None:
            self.mongo_client.close()
            self.mongo_client = None
            self.mongo_db = None


database = Database()


@contextmanager
def get_pg_cursor(commit: bool = False) -> Iterator[RealDictCursor]:
    if database.pg_pool is None:
        database.connect()

    conn = database.pg_pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            yield cursor
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        database.pg_pool.putconn(conn)


def get_mongo_db():
    if database.mongo_db is None:
        database.connect()
    return database.mongo_db


def initialize_database() -> None:
    schema_path = BASE_DIR / "database" / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(schema_sql)

    mongo_db = get_mongo_db()
    mongo_db.saved_jobs.create_index(
        [("user_id", ASCENDING), ("job_id", ASCENDING)], unique=True
    )
    mongo_db.saved_jobs.create_index([("user_id", ASCENDING), ("saved_at", DESCENDING)])
    mongo_db.search_history.create_index(
        [("user_id", ASCENDING), ("created_at", DESCENDING)]
    )
    mongo_db.chat_messages.create_index(
        [("conversation_id", ASCENDING), ("created_at", DESCENDING)]
    )
    mongo_db.chat_messages.create_index(
        [("sender_user_id", ASCENDING), ("created_at", DESCENDING)]
    )
    mongo_db.conversations.create_index(
        [("job_id", ASCENDING), ("application_id", ASCENDING), ("owner_user_id", ASCENDING), ("applicant_user_id", ASCENDING)],
        unique=True,
    )
    mongo_db.conversations.create_index(
        [("owner_user_id", ASCENDING), ("applicant_user_id", ASCENDING)]
    )
    mongo_db.conversations.create_index(
        [("owner_user_id", ASCENDING), ("last_message_at", DESCENDING)]
    )
    mongo_db.conversations.create_index(
        [("applicant_user_id", ASCENDING), ("last_message_at", DESCENDING)]
    )
