from __future__ import annotations

import hashlib
import sqlite3
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.paths import DATA_DIR, DB_PATH
from src.portfolio.base import Holding
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
    results_filed_for TEXT,
    pack_sent_for TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_id INTEGER,
    x_kpi REAL,
    x_book REAL,
    x_industry REAL,
    x_price REAL,
    x_guidance REAL,
    S REAL,
    band TEXT,
    low_confidence INTEGER NOT NULL DEFAULT 0,
    active_factors TEXT,
    triage_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS holdings_cache (
    symbol TEXT PRIMARY KEY,
    isin TEXT NOT NULL DEFAULT '',
    qty REAL NOT NULL,
    avg_cost REAL NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extractions (
    filing_hash TEXT PRIMARY KEY,
    filing_id INTEGER,
    text TEXT,
    text_chars INTEGER NOT NULL DEFAULT 0,
    needs_manual_read INTEGER NOT NULL DEFAULT 0,
    kpis_json TEXT,
    model TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kpi_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    kpi_name TEXT NOT NULL,
    period TEXT NOT NULL,
    value REAL NOT NULL,
    source_filing_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(ticker, kpi_name, period)
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    action TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    S_at_time REAL,
    anticipatory INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS condition_touches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    condition_text TEXT NOT NULL,
    severity TEXT NOT NULL,
    check_kind TEXT NOT NULL,
    filing_id INTEGER,
    touched_at TEXT NOT NULL
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
        filing_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(filings)")}
        if "collapsed_into" not in filing_cols:
            self.conn.execute("ALTER TABLE filings ADD COLUMN collapsed_into INTEGER")
        score_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(scores)")}
        if score_cols and "active_factors" not in score_cols:
            self.conn.execute("ALTER TABLE scores ADD COLUMN active_factors TEXT")
        if score_cols and "low_confidence" not in score_cols:
            self.conn.execute(
                "ALTER TABLE scores ADD COLUMN low_confidence INTEGER NOT NULL DEFAULT 0"
            )
        decision_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(decisions)")}
        if decision_cols and "anticipatory" not in decision_cols:
            self.conn.execute(
                "ALTER TABLE decisions ADD COLUMN anticipatory INTEGER NOT NULL DEFAULT 0"
            )
        state_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(ticker_state)")}
        if "pack_sent_for" not in state_cols:
            self.conn.execute("ALTER TABLE ticker_state ADD COLUMN pack_sent_for TEXT")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def filing_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM filings").fetchone()
        return int(row["n"])

    def score_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM scores").fetchone()
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

    def insert_score(
        self,
        *,
        filing_id: int | None,
        x_kpi: float | None,
        x_book: float | None,
        x_industry: float | None,
        x_price: float | None,
        x_guidance: float | None,
        S: float | None,
        band: str | None,
        low_confidence: bool,
        active_factors: tuple[str, ...] | list[str],
        triage_json: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO scores (
                filing_id, x_kpi, x_book, x_industry, x_price, x_guidance,
                S, band, low_confidence, active_factors, triage_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                filing_id,
                x_kpi,
                x_book,
                x_industry,
                x_price,
                x_guidance,
                S,
                band,
                int(low_confidence),
                ",".join(active_factors),
                triage_json,
                _utcnow(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def replace_holdings_cache(self, holdings: list[Holding]) -> None:
        now = _utcnow()
        self.conn.execute("DELETE FROM holdings_cache")
        self.conn.executemany(
            """
            INSERT INTO holdings_cache (symbol, isin, qty, avg_cost, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (h.symbol, h.isin, h.qty, h.avg_cost, now)
                for h in holdings
            ],
        )
        self.conn.commit()

    def holdings_cache(self) -> list[Holding]:
        rows = self.conn.execute(
            "SELECT symbol, isin, qty, avg_cost FROM holdings_cache ORDER BY symbol"
        ).fetchall()
        return [
            Holding(
                symbol=row["symbol"],
                isin=row["isin"],
                qty=float(row["qty"]),
                avg_cost=float(row["avg_cost"]),
            )
            for row in rows
        ]

    def get_extraction(self, filing_hash: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM extractions WHERE filing_hash = ?",
            (filing_hash,),
        ).fetchone()

    def save_extraction(
        self,
        *,
        filing_hash: str,
        filing_id: int | None,
        text: str,
        needs_manual_read: bool,
        kpis_json: dict | None,
        model: str | None,
    ) -> None:
        import json

        self.conn.execute(
            """
            INSERT INTO extractions (
                filing_hash, filing_id, text, text_chars, needs_manual_read,
                kpis_json, model, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(filing_hash) DO NOTHING
            """,
            (
                filing_hash,
                filing_id,
                text,
                len(text),
                int(needs_manual_read),
                json.dumps(kpis_json, ensure_ascii=False) if kpis_json is not None else None,
                model,
                _utcnow(),
            ),
        )
        self.conn.commit()

    def insert_kpi_print(
        self,
        *,
        ticker: str,
        kpi_name: str,
        period: str,
        value: float,
        source_filing_id: int | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO kpi_series (
                ticker, kpi_name, period, value, source_filing_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, kpi_name, period) DO UPDATE SET
                value = excluded.value,
                source_filing_id = excluded.source_filing_id
            """,
            (ticker, kpi_name, period, value, source_filing_id, _utcnow()),
        )
        self.conn.commit()

    def kpi_qoq_history(self, symbol: str) -> list[float]:
        names = [
            row["kpi_name"]
            for row in self.conn.execute(
                "SELECT DISTINCT kpi_name FROM kpi_series WHERE ticker = ?",
                (symbol,),
            )
        ]
        best: list[float] = []
        for name in names:
            levels = [
                float(row["value"])
                for row in self.conn.execute(
                    """
                    SELECT value FROM kpi_series
                    WHERE ticker = ? AND kpi_name = ?
                    ORDER BY id
                    """,
                    (symbol, name),
                )
            ]
            qoq: list[float] = []
            for prev, cur in zip(levels, levels[1:]):
                if prev == 0:
                    continue
                qoq.append((cur - prev) / abs(prev))
            if len(qoq) > len(best):
                best = qoq
        return best

    def filings_for(
        self,
        symbol: str,
        *,
        limit: int = 20,
        since: date | None = None,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT filed_at, category, subcategory, headline, filter_status
            FROM filings
            WHERE ticker = ?
        """
        params: list[object] = [symbol]
        if since is not None:
            sql += " AND filed_at IS NOT NULL AND date(filed_at) >= ?"
            params.append(since.isoformat())
        sql += " ORDER BY filed_at DESC, id DESC LIMIT ?"
        params.append(limit)
        return list(self.conn.execute(sql, params).fetchall())

    def kpi_prints_for(self, symbol: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT kpi_name, period, value, source_filing_id
                FROM kpi_series
                WHERE ticker = ?
                ORDER BY kpi_name, id
                """,
                (symbol,),
            ).fetchall()
        )

    def latest_score(self, symbol: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT s.S, s.band, s.low_confidence, s.active_factors,
                   s.x_kpi, s.x_book, s.x_industry, s.x_price, s.x_guidance
            FROM scores s
            JOIN filings f ON f.id = s.filing_id
            WHERE f.ticker = ?
            ORDER BY s.id DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()

    def latest_S(self, symbol: str) -> float | None:
        row = self.latest_score(symbol)
        if row is None or row["S"] is None:
            return None
        return float(row["S"])

    def insert_decision(
        self,
        *,
        ticker: str,
        action: str,
        note: str = "",
        S_at_time: float | None = None,
        anticipatory: bool = False,
        decided_at: datetime | None = None,
    ) -> int:
        when = decided_at.astimezone(UTC).isoformat(timespec="seconds") if decided_at else _utcnow()
        cur = self.conn.execute(
            """
            INSERT INTO decisions (
                ticker, decided_at, action, note, S_at_time, anticipatory
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ticker,
                when,
                action,
                note,
                S_at_time,
                int(anticipatory),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def decisions_for(
        self,
        symbol: str | None = None,
        *,
        anticipatory: bool | None = None,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM decisions WHERE 1=1"
        params: list[object] = []
        if symbol is not None:
            sql += " AND ticker = ?"
            params.append(symbol)
        if anticipatory is True:
            sql += " AND anticipatory = 1"
        elif anticipatory is False:
            sql += " AND anticipatory = 0"
        sql += " ORDER BY decided_at DESC, id DESC"
        return list(self.conn.execute(sql, params).fetchall())

    def touch_condition(
        self,
        *,
        ticker: str,
        text: str,
        severity: str,
        check: str,
        filing_id: int | None = None,
        touched_at: date | datetime | None = None,
    ) -> int:
        if isinstance(touched_at, datetime):
            when = touched_at.date().isoformat()
        elif isinstance(touched_at, date):
            when = touched_at.isoformat()
        else:
            when = datetime.now(tz=IST).date().isoformat()
        cur = self.conn.execute(
            """
            INSERT INTO condition_touches (
                ticker, condition_text, severity, check_kind, filing_id, touched_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ticker, text, severity, check, filing_id, when),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def touches_in_window(
        self,
        symbol: str,
        *,
        since: date,
        until: date,
    ) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT * FROM condition_touches
                WHERE ticker = ?
                  AND date(touched_at) >= ?
                  AND date(touched_at) <= ?
                ORDER BY touched_at, id
                """,
                (symbol, since.isoformat(), until.isoformat()),
            ).fetchall()
        )

    def current_touches(self, symbol: str, *, as_of: date | None = None) -> list[sqlite3.Row]:
        end = as_of or datetime.now(tz=IST).date()
        start = end - timedelta(days=182)
        rows = self.touches_in_window(symbol, since=start, until=end)
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest[str(row["condition_text"])] = row
        return list(latest.values())

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.conn.commit()

    def pack_sent_for(self, symbol: str) -> date | None:
        row = self._state(symbol)
        if not row or not row["pack_sent_for"]:
            return None
        return date.fromisoformat(row["pack_sent_for"])

    def mark_pack_sent(self, symbol: str, due: date) -> None:
        self._upsert_state(symbol, pack_sent_for=due.isoformat())

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
