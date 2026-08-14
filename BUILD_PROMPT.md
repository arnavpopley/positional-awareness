# Build prompt (paste into a new Agent chat on this repo)

Read `SPEC.md` and `.cursor/rules/` first. Then implement **Phase 0 only**. Do not start Phase 1 until Phase 0 has shipped against the acceptance test in SPEC.md §7.

## Phase 0

1. `config/tickers.yaml` loaded from `config/tickers.example.yaml` shape. Refuse to watch a name with no thesis or no KPI.
2. BSE source behind `Source.fetch(ticker, since) -> list[Filing]`. Browser-like headers. Fixture: save one real `AnnGetData` response under `tests/fixtures/` **before** writing the filter.
3. Dedupe on `(exchange, ann_id or pdf_url)`. SQLite in `data/` (gitignored).
4. `filter.py` kill / low / candidate lists exactly as SPEC.md §4. Unknown → candidate.
5. CLI table: symbol, qty, avg cost, last price, return, thesis (short), next event if any.
6. Delayed quotes for last price (Yahoo or equivalent). Not a live ticker. Not vs Nifty.
7. macOS notification for **candidate** filings only (headline + link). No Telegram.
8. Scheduler: ordinary days at 09:30 / 12:30 / 16:00 / 19:00 IST; ~20 min only for tickers with results due in the next few days; few-minute poll on that ticker’s results morning; overnight off except optional 08:00 IST. Never faster than 15 minutes.

## Acceptance

A board-meeting intimation or results filing for a held ticker produces a macOS notification inside the cadence window. A trading-window closure is stored as killed and does **not** notify.

## Hard no

Web UI, Telegram, Groww orders, NSE (unless a ticker is NSE-only), Ollama, Nifty residual, weight tuning, RSI, news RSS, predicted earnings beats, auth, FastAPI, broker execution.

Gemini is **Phase 1**. Do not add LLM scoring until Phase 0 ships.

Each module must run standalone (`uv run python -m src.sources.bse SYMBOL`). Python 3.12 + uv.

When Phase 0 is done, stop and report how to run it. Do not “just continue” into Phase 1.
