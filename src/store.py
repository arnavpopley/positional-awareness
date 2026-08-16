from __future__ import annotations

import hashlib
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.paths import DATA_DIR, DB_PATH
from src.sources.base import Filing

IST = ZoneInfo("Asia/Kolkata")

SCHEMA = """
CREATE TABLE IF NOT EXISTS filings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    exchange TEXT NOT NULL,
    ann_id TEXT,
    category TEXT NOT NULL DEFAULT '',
    subcategory TEXT NOT NULL DEFAULT '',
    headline TEXT NOT NULL DEFAULT '',
    pdf_url TEXT,
    filed_at TEXT,
    hash TEXT,
    filter_status TEXT NOT NULL,
    collapsed_into INTEGER,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS filings_exchange_ann
    ON filings(exchange, ann_id)
    WHERE ann_id IS NOT NULL AND trim(ann_id) != '';
CREATE UNIQUE INDEX IF NOT EXISTS filings_exchange_pdf
    ON filings(exchange, pdf_url)
    WHERE (ann_id IS NULL OR trim(ann_id) = '')
      AND pdf_url IS NOT NULL AND trim(pdf_url) != '';

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_id INTEGER NOT NULL REFERENCES filings(id),
    channel TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    UNIQUE(filing_id, channel)
);

CREATE TABLE IF NOT EXISTS ticker_state (
    symbol TEXT PRIMARY KEY,
    results_due TEXT,
    last_fetch_at TEXT,
    results_filed_for TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _utcnow() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def filing_hash(filing: Filing) -> str:
    key = f"{filing.exchange}|{filing.ann_id or ''}|{filing.pdf_url or ''}"
    return hashlib.sha256(key.encode()).hexdigest()


class Store:
    def __init__(self, path: Path | None = None) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(filings)")}
        if "collapsed_into" not in cols:
            self.conn.execute("ALTER TABLE filings ADD COLUMN collapsed_into INTEGER")
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def filing_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM filings").fetchone()
        return int(row["n"])

    def exists(self, filing: Filing) -> bool:
        if filing.ann_id:
            row = self.conn.execute(
                "SELECT 1 FROM filings WHERE exchange = ? AND ann_id = ?",
                (filing.exchange, filing.ann_id),
            ).fetchone()
            if row:
                return True
        if filing.pdf_url:
            row = self.conn.execute(
                "SELECT 1 FROM filings WHERE exchange = ? AND pdf_url = ?",
                (filing.exchange, filing.pdf_url),
            ).fetchone()
            if row:
                return True
        return False

    def insert_filing(self, filing: Filing, status: str) -> int | None:
        if self.exists(filing):
            return None
        filed = filing.filed_at.isoformat() if filing.filed_at else None
        try:
            cur = self.conn.execute(
                """
                INSERT INTO filings (
                    ticker, exchange, ann_id, category, subcategory,
                    headline, pdf_url, filed_at, hash, filter_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    filing.ticker,
                    filing.exchange,
                    filing.ann_id,
                    filing.category,
                    filing.subcategory,
                    filing.headline,
                    filing.pdf_url,
                    filed,
                    filing_hash(filing),
                    status,
                    _utcnow(),
                ),
            )
            self.conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return None

    def mark_collapsed(self, filing_id: int, into_id: int) -> None:
        self.conn.execute(
            "UPDATE filings SET collapsed_into = ? WHERE id = ?",
            (into_id, filing_id),
        )
        self.conn.commit()

    def collapse_outcome_into_results(self, ticker: str) -> set[int]:
        """Mark BM outcomes that duplicate a results print in a 24h window.

        Returns filing ids that must not be notified.
        """
        suppressed: set[int] = set()
        outcomes = self.conn.execute(
            """
            SELECT id, filed_at FROM filings
            WHERE ticker = ?
              AND category = 'Board Meeting'
              AND subcategory = 'Outcome of Board Meeting'
            """,
            (ticker,),
        ).fetchall()
        results = self.conn.execute(
            """
            SELECT id, filed_at FROM filings
            WHERE ticker = ?
              AND category = 'Result'
              AND subcategory = 'Financial Results'
            """,
            (ticker,),
        ).fetchall()
        window = 24 * 3600
        for outcome in outcomes:
            if not outcome["filed_at"]:
                continue
            ot = datetime.fromisoformat(outcome["filed_at"])
            for result in results:
                if not result["filed_at"]:
                    continue
                rt = datetime.fromisoformat(result["filed_at"])
                if ot.tzinfo is None and rt.tzinfo is not None:
                    ot = ot.replace(tzinfo=rt.tzinfo)
                if rt.tzinfo is None and ot.tzinfo is not None:
                    rt = rt.replace(tzinfo=ot.tzinfo)
                if abs((ot - rt).total_seconds()) <= window:
                    self.mark_collapsed(outcome["id"], result["id"])
                    suppressed.add(int(outcome["id"]))
                    break
        return suppressed

    def alert_sent(self, filing_id: int, channel: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM alerts WHERE filing_id = ? AND channel = ?",
            (filing_id, channel),
        ).fetchone()
        return row is not None

    def record_alert(self, filing_id: int, channel: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO alerts (filing_id, channel, sent_at) VALUES (?, ?, ?)",
            (filing_id, channel, _utcnow()),
        )
        self.conn.commit()

    def _state(self, symbol: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM ticker_state WHERE symbol = ?", (symbol,)
        ).fetchone()

    def _upsert_state(self, symbol: str, **fields: str | None) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO ticker_state (symbol) VALUES (?)", (symbol,)
        )
        assignments = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [symbol]
        self.conn.execute(
            f"UPDATE ticker_state SET {assignments} WHERE symbol = ?", values
        )
        self.conn.commit()

    def results_due(self, symbol: str) -> date | None:
        row = self._state(symbol)
        if not row or not row["results_due"]:
            return None
        return date.fromisoformat(row["results_due"])

    def set_results_due(self, symbol: str, due: date) -> None:
        existing = self.results_due(symbol)
        if existing and existing >= due:
            return
        self._upsert_state(symbol, results_due=due.isoformat())

    def mark_results_filed(self, symbol: str, due: date | None = None) -> None:
        target = due or self.results_due(symbol)
        if target is None:
            return
        self._upsert_state(symbol, results_filed_for=target.isoformat())

    def results_filed_for(self, symbol: str) -> date | None:
        row = self._state(symbol)
        if not row or not row["results_filed_for"]:
            return None
        return date.fromisoformat(row["results_filed_for"])

    def last_fetch_at(self, symbol: str) -> datetime | None:
        row = self._state(symbol)
        if not row or not row["last_fetch_at"]:
            return None
        return datetime.fromisoformat(row["last_fetch_at"])

    def touch_fetch(self, symbol: str, when: datetime) -> None:
        self._upsert_state(symbol, last_fetch_at=when.isoformat())

    def next_event(self, symbol: str) -> str | None:
        due = self.results_due(symbol)
        if due is None:
            return None
        filed = self.results_filed_for(symbol)
        if filed == due:
            return None
        today = datetime.now(tz=IST).date()
        if due < today:
            return None
        return f"Results due {due.isoformat()}"


def main(argv: list[str] | None = None) -> int:
    del argv
    store = Store()
    n = store.filing_count()
    print(f"db={store.path} filings={n}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
