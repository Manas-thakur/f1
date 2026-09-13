from __future__ import annotations

import sqlite3
from pathlib import Path


class ControlState:
    def __init__(self, path: Path | None = None) -> None:
        database = ":memory:" if path is None else str(path)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS control_state "
            "(id INTEGER PRIMARY KEY CHECK (id = 1), selected_car_id TEXT NOT NULL)"
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO control_state (id, selected_car_id) VALUES (1, 'car-01')"
        )
        self.connection.commit()

    def selected(self) -> str:
        row = self.connection.execute("SELECT selected_car_id FROM control_state WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("control state is missing")
        return str(row[0])

    def select(self, car_id: str) -> None:
        self.connection.execute("UPDATE control_state SET selected_car_id = ? WHERE id = 1", (car_id,))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
