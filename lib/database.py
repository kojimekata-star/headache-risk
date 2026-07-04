import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent.parent / "data" / "headache.db"


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS headache_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            onset_at   TEXT NOT NULL,
            end_at     TEXT,
            intensity  INTEGER CHECK(intensity BETWEEN 1 AND 10),
            notes      TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS medications (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            headache_event_id  INTEGER NOT NULL REFERENCES headache_events(id) ON DELETE CASCADE,
            drug_name          TEXT NOT NULL,
            dose_amount        REAL,
            dose_unit          TEXT DEFAULT 'mg',
            taken_at           TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fitbit_tokens (
            id            INTEGER PRIMARY KEY,
            access_token  TEXT,
            refresh_token TEXT,
            expires_at    INTEGER,
            fitbit_user_id TEXT
        );

        CREATE TABLE IF NOT EXISTS fitbit_sleep (
            date       TEXT PRIMARY KEY,
            sleep_start TEXT,
            sleep_end   TEXT,
            duration_min INTEGER,
            efficiency   INTEGER,
            deep_min     INTEGER,
            light_min    INTEGER,
            rem_min      INTEGER,
            wake_min     INTEGER
        );

        CREATE TABLE IF NOT EXISTS fitbit_hrv (
            date       TEXT PRIMARY KEY,
            rmssd      REAL,
            resting_hr INTEGER,
            coverage   REAL
        );

        CREATE TABLE IF NOT EXISTS pressure_log (
            timestamp    TEXT NOT NULL,
            pressure_hpa REAL,
            lat          REAL,
            lon          REAL,
            PRIMARY KEY (timestamp, lat, lon)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        INSERT OR IGNORE INTO settings (key, value) VALUES ('lat', '35.6762');
        INSERT OR IGNORE INTO settings (key, value) VALUES ('lon', '139.6503');
        INSERT OR IGNORE INTO settings (key, value) VALUES ('location_name', '東京');
        """)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))
