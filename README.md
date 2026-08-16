# Positional Awareness

Stay involved with holdings without re-learning the business. Spec is the source of truth.

- **[SPEC.md](SPEC.md)** — locked product, scorecard, workflow, phases
- **[BUILD_PROMPT.md](BUILD_PROMPT.md)** — paste this into a **new Agent chat** opened on this folder

v1 is CLI + macOS notify. Telegram later. Gemini in Phase 1. Phase 0 has no LLM.

## Fill in

Copy `config/tickers.example.yaml` to `config/tickers.yaml` and write real theses + KPIs. No thesis, no tracking.

```bash
cp config/tickers.example.yaml config/tickers.yaml
```

## Phase 0

Python 3.12 + [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
```

| Command | What |
|---|---|
| `uv run pos` | Holdings table (delayed last price, return vs cost, thesis, next event). Prints thesis-less holdings count from cache. |
| `uv run pos --no-quotes` | Same table, skip the quote fetch |
| `uv run pos sync` | Read-only Groww holdings vs ledger. Reports missing thesis / not-held / qty-cost drift. Never writes the ledger. |
| `uv run python -m src.main --once` | One poll of BSE for ledger names. First run stores silently; later runs notify **candidate** filings |
| `uv run python -m src.main --once --fixture tests/fixtures/anngetdata.json --notify-backfill` | Replay the saved BSE JSON (board meeting / results notify; trading-window does not) |
| `uv run python -m src.main` | Scheduler: 09:30 / 12:30 / 16:00 / 19:00 IST weekdays, 08:00 IST daily, 15-minute floor for results-week / results-morning |
| `uv run python -m src.sources.bse SUZLON` | Fetch announcements for one name |
| `uv run python -m src.filter` | Classify the fixture |
| `uv run python -m src.notify` | Test a macOS notification |
| `uv run python -m src.extract path/to.pdf` | pdfplumber text extract (no Gemini). Caps at ~15k chars. |
| `uv run pytest` | Filter + dedupe + cadence + extract tests |

Keep the scheduler alive with `config/launchd.plist.example` (replace `REPO`). Never faster than 15 minutes.

Do not implement from a cold chat without SPEC.md and BUILD_PROMPT.md.
