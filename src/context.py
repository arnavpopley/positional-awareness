from __future__ import annotations

import sys
from datetime import date

from src.ledger import LedgerError, Ticker, by_symbol, load_tickers
from src.store import Store


def _fmt_qty(qty: float) -> str:
    if qty == int(qty):
        return str(int(qty))
    return f"{qty:.2f}"


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


def render_context(
    ticker: Ticker,
    store: Store,
    *,
    filings_n: int = 20,
    since: date | None = None,
    last: float | None = None,
) -> str:
    """Markdown export from ledger + local SQLite. No network."""
    lines: list[str] = [
        f"# {ticker.symbol}",
        "",
        f"- status: {ticker.status}",
        f"- quantity: {_fmt_qty(ticker.qty)}",
        f"- average cost: {_fmt_price(ticker.avg_cost)}",
        f"- last price: {_fmt_price(last)}",
        "",
        "## Thesis",
        "",
        ticker.thesis or "(none)",
        "",
        "## Conditions",
        "",
    ]
    quantitative = [c for c in ticker.conditions if c.check == "quantitative"]
    manual = [c for c in ticker.conditions if c.check == "manual"]
    lines.append("### Quantitative")
    lines.append("")
    if quantitative:
        for cond in quantitative:
            extra = [cond.severity]
            if cond.kpi:
                extra.append(f"kpi={cond.kpi}")
            if cond.threshold:
                extra.append(cond.threshold)
            lines.append(f"- {cond.text} ({'; '.join(extra)})")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("### Manual")
    lines.append("")
    if manual:
        for cond in manual:
            tag = f" [{cond.source}]" if cond.source else ""
            lines.append(f"- {cond.text} ({cond.severity}){tag}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Currently touched")
    lines.append("")
    touched = store.current_touches(ticker.symbol)
    if touched:
        for row in touched:
            lines.append(
                f"- {row['touched_at']} {row['condition_text']} "
                f"({row['severity']}, {row['check_kind']})"
            )
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append(f"## Filings (last {filings_n})")
    lines.append("")
    rows = store.filings_for(ticker.symbol, limit=filings_n, since=since)
    if rows:
        lines.append("| date | category | subcategory | headline | filter |")
        lines.append("|---|---|---|---|---|")
        for row in rows:
            filed = row["filed_at"] or "—"
            if "T" in str(filed):
                filed = str(filed).split("T", 1)[0]
            headline = " ".join(str(row["headline"] or "").split()).replace("|", "/")
            lines.append(
                f"| {filed} | {row['category'] or ''} | {row['subcategory'] or ''} "
                f"| {headline} | {row['filter_status']} |"
            )
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## KPI history")
    lines.append("")
    prints = store.kpi_prints_for(ticker.symbol)
    if prints:
        current = None
        for row in prints:
            name = row["kpi_name"]
            if name != current:
                if current is not None:
                    lines.append("")
                lines.append(f"### {name}")
                lines.append("")
                current = name
            lines.append(f"- {row['period']}: {row['value']}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Decisions")
    lines.append("")
    decisions = store.decisions_for(ticker.symbol)
    if decisions:
        for row in decisions:
            flag = " anticipatory" if row["anticipatory"] else ""
            s_bit = f" S={row['S_at_time']}" if row["S_at_time"] is not None else ""
            note = row["note"] or ""
            when = str(row["decided_at"]).split("T", 1)[0]
            lines.append(f"- {when} {row['action']}{flag}{s_bit} {note}".rstrip())
    else:
        lines.append("(none)")
    lines.append("")
    return "\n".join(lines)


def context_command(
    symbol: str,
    *,
    filings_n: int = 20,
    since: date | None = None,
    store: Store | None = None,
    tickers: list[Ticker] | None = None,
) -> int:
    own_store = store is None
    store = store or Store()
    try:
        book = tickers if tickers is not None else load_tickers()
        ticker = by_symbol(book, symbol)
        print(render_context(ticker, store, filings_n=filings_n, since=since, last=None))
        return 0
    except LedgerError as exc:
        print(f"pos context: {exc}", file=sys.stderr)
        return 1
    finally:
        if own_store:
            store.close()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m src.context TICKER [--filings N] [--since YYYY-MM-DD]", file=sys.stderr)
        return 2
    symbol = args[0]
    filings_n = 20
    since = None
    rest = args[1:]
    i = 0
    while i < len(rest):
        if rest[i] == "--filings" and i + 1 < len(rest):
            filings_n = int(rest[i + 1])
            i += 2
            continue
        if rest[i] == "--since" and i + 1 < len(rest):
            since = date.fromisoformat(rest[i + 1])
            i += 2
            continue
        print(f"context: unknown argument {rest[i]}", file=sys.stderr)
        return 2
    return context_command(symbol, filings_n=filings_n, since=since)


if __name__ == "__main__":
    raise SystemExit(main())
