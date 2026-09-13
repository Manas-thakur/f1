from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import psycopg


class ControlState:
    def __init__(self, path: Path | None = None, *, database_url: str | None = None) -> None:
        self.postgres = None
        resolved_url = database_url or os.environ.get("DATABASE_URL")
        if resolved_url:
            self.sqlite = None
            self.postgres = psycopg.connect(resolved_url)
            return
        database = ":memory:" if path is None else str(path)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.sqlite = sqlite3.connect(database, check_same_thread=False)
        self.sqlite.execute(
            "CREATE TABLE IF NOT EXISTS control_state "
            "(id INTEGER PRIMARY KEY CHECK (id = 1), selected_car_id TEXT NOT NULL)"
        )
        self.sqlite.execute(
            "INSERT OR IGNORE INTO control_state (id, selected_car_id) VALUES (1, 'car-01')"
        )
        self.sqlite.commit()

    def selected(self) -> str:
        if self.postgres is not None:
            row = self.postgres.execute(
                "SELECT selected_car_id FROM public.control_state WHERE id = 1"
            ).fetchone()
        else:
            assert self.sqlite is not None
            row = self.sqlite.execute("SELECT selected_car_id FROM control_state WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("control state is missing")
        return str(row[0])

    def select(self, car_id: str) -> None:
        if self.postgres is not None:
            self.postgres.execute(
                "UPDATE public.control_state SET selected_car_id = %s, updated_at = now() WHERE id = 1",
                (car_id,),
            )
            self.postgres.commit()
            return
        assert self.sqlite is not None
        self.sqlite.execute("UPDATE control_state SET selected_car_id = ? WHERE id = 1", (car_id,))
        self.sqlite.commit()

    def close(self) -> None:
        if self.postgres is not None:
            self.postgres.close()
        if self.sqlite is not None:
            self.sqlite.close()
