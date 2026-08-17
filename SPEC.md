# Positional Awareness

Personal, single-user tool. Stay involved with holdings over time without re-learning the business. Each name keeps its thesis and KPI history on the row. When facts change, you get the **named KPI evidence and the scorecard arithmetic**. **You click Groww.** This agent never places orders.

This is not a scanner, not a broker, not a Nifty-alpha engine, not a news-sentiment firehose.

---

## 1. Job

You buy for a reason, then the name stays in the book and the reason evaporates. This tool:

- Keeps **thesis + 1–3 named KPIs** (revenue, PAT, deliveries, order book, …) on each row, with a quarter-by-quarter series.
- Wakes you when earnings are a few days out, and when a print/order/news/price move would change what to do.
- Shows a **frozen, visible scorecard** (S and the five factor lines). Bands are descriptive labels, not instructions.
- Lets you pre-position before results **if you are already confident**, or wait with one KPI in mind and act after confirmation.

Involvement ≠ more trades. A quiet week is success.

Expected cadence for ~10 names: glance at prints (~40/year, most no change); **a handful of real position changes a year**; optional earnings plays on 0–1 names per results week. Do not nag daily.

---

## 2. Non-goals (do not build)

- Broker order placement (Groww/Kite). Read-only holdings via `pos sync` (cached). Ledger stays hand-edited. Never orders.
- Live streaming prices, websockets, RSI/MACD stacks.
- **Nifty-relative / excess-return alpha.** This book is allowed to diverge from the index. Price factor is the **name’s own move**.
- Multi-user, auth, deploy-for-others. The page binds to localhost.
- Predicted beats/misses. No “the model thinks the quarter will beat.”
- Screening / stock discovery.
- Twitter / broker-target / mood APIs.
- Tuning scorecard weights in beta.
- **Telegram in v1.** CLI + macOS notifications first. Telegram is a later push channel, not a blocker.
- Public or multi-user web app. A **read-only local page** (FastAPI, `127.0.0.1`) is allowed now that the poller works. Same ledger and SQLite as the CLI. No orders, no websockets, no live ticker.
- NSE source unless a name is NSE-only (BSE covers dual-listed).
- Local Ollama (16 GB M5; do not slow the laptop). Gemini API (key already exists). Groq+Llama optional fallback.

---

## 3. Beta scorecard (frozen — do not tune)

Weights are frozen:

```
w_kpi=0.40  w_book=0.20  w_industry=0.15  w_price=0.15  w_guidance=0.10
```

Each factor returns `(x ∈ [−1, +1], active: bool)`. **Inactive is not zero.** Zero means the factor fired and the evidence was flat. Missing data (no KPI print, no peer print, no guidance) sets `active=false` and drops that weight from the denominator.

```
S = Σ (w_i · x_i for active i) / Σ (w_i for active i)
```

If no factors are active, S is **undefined** (`None`). Emit no band. If fewer than two factors are active, mark **`low_confidence`** and **suppress the band**; still show the five factor lines. Inactive lines render as `n/a`, never `0.00`.

| Factor | w | Raw | Normalization |
|---|---|---|---|
| Thesis KPI print | 0.40 | QoQ % of the named KPI(s) from results/PPT | Winsorize at ±25%, then `/ 0.25`. No print → inactive |
| Order book / ops filings | 0.20 | Book YoY % or order vs quarterly sales | Same winsorize; one-off order: `sign * min(1, order/q_sales)`. No filing → inactive |
| Industry | 0.15 | **v1: peer prints** from other ledger names with the same sector tag. RSS news later. | Mean of peer KPI z vs their own history. No peers / unrelated → inactive |
| Own price | 0.15 | 20-day return of **this name**. Alert if \|1d\| > 3% or \|5d\| > 8% | Winsorize at ±15%, then `/ 0.15`. **Not vs Nifty**. No quote → inactive |
| Guidance | 0.10 | PPT/con-call vs last guidance, **only if it names your KPI** | Maps to {−1, 0, +1} when present. Else inactive |

**Not inside S**

- **Your confidence (0–100):** disagreement flag. If mapped S vs stamp differs by > 25 points, say so. Do not mix a stale 80% into S (it blocks a broken KPI).
- **Position weight:** size context only. A name already ≥ **20%** of the book is noted; it does not change S.
- **Days to results:** switches the message (pack vs post-print). Does not change S.
- **`needs_manual_read`:** the number is unconfirmed until the user reads the filing.

**S → descriptive band** (not an instruction)

| S | Label |
|---|---|
| ≥ +0.60 | strongly positive |
| +0.25 to +0.60 | positive |
| −0.25 to +0.25 | neutral |
| −0.60 to −0.25 | negative |
| ≤ −0.60 | strongly negative |

Gemini **extracts numbers** from PDFs/text. The weighted sum is **deterministic** (`src/score.py` `score_extraction`). Show the five lines (`raw → x → w·x`) in every rec. Persist `active_factors` next to S. `needs_manual_read` suppresses the band.

A **hit** for later evaluation: did the named KPI subsequently confirm the call? Not “did the stock beat Nifty.”

---

## 4. Workflow

### 0. Setup (once per name)

User supplies: why they own it, 1–3 conditions (quantitative KPIs and/or manual checks), qty + avg cost, confidence, optional sector, BSE scrip code, **status**.  
LLM drafts thesis + conditions. **User confirms before write.** Status is never auto-assigned; omitting it defaults to `held`, which refuses to load without a thesis and at least one condition.

**Ledger statuses**

| status | Poll | Score | Conditions | Surface |
|---|---|---|---|---|
| `held` (default) | full | yes | thesis + ≥1 condition required | CLI, notify, context |
| `exiting` | results and board-meeting intimations only | no | optional | CLI, those notifies |
| `event` | no | no | optional | CLI table and weekly nudge only |
| `no_thesis` | no | no | optional | `pos sync` + top of CLI table as outstanding |
| `manual` | no (ETFs / no filings) | no | optional | CLI table and weekly nudge only |

**Conditions**

```
conditions:
  - text: "Order inflow stops growing"
    check: quantitative
    kpi: order_inflow_ttm
    threshold: "YoY decline for 2 consecutive quarters"
    severity: material
  - text: "Moat erodes, story stops making sense"
    check: manual
    severity: watch
```

Every condition requires `severity`: `structural` (the reason the position exists stops being true), `material` (real deterioration), or `watch` (worth knowing, weak on its own). Conditions are **not** individual exit triggers. Touches are stored with severity and date. Escalation is evaluated on **count and severity** inside a rolling **2-quarter** window (~182 days):

| Window | Result |
|---|---|
| 1 watch or 1 material | record only, no notification |
| 2 material, or 1 structural | review, notify |
| 3+ material, or 1 structural + 1 material | priority review, notify |

Never emit an action verb at any level. `check: quantitative` feeds named KPIs into extract/S. `check: manual` can be flagged as touched and **counts toward escalation**, but **never activates a scoring factor or changes the band**. Shared blocks live in the same `config/tickers.yaml` under `shared_conditions` and are referenced as `conditions_include: [quality_default]`. They merge ahead of entry-level conditions. Legacy `kpis:` rows still parse as quantitative conditions if they carry severity.

### 1. Always on

| Clock | What |
|---|---|
| Ordinary days | A few fixed IST slots (e.g. 09:30, 12:30, 16:00, 19:00). **Not** every 20 min. |
| Name has results due in the next few days | ~20 min for **that scrip only** |
| Results morning for that name | Every few minutes until results/PPT filing is in |
| Overnight / weekend | Off, or one pass ~08:00 IST |

BSE corporate announcements for **your scrip codes only** (same JSON the BSE site uses). Dedupe on `(exchange, announcement id or pdf url)`. Kill-list before any LLM call. Be polite: cache, back off, never faster than 15 min even on results morning. Unofficial feed — wrap in `Source.fetch(ticker, since)` so a break is a one-file fix.

Quote snapshot (delayed, not a live ticker) → return vs cost on the row.

### 2. Events

| Event | Extract | User gets |
|---|---|---|
| Board-meeting intimation | Results date. S unchanged | “Results due [date].” Pack queued |
| Few days out / evening before | Pack: 2-sentence thesis, KPI to watch, last 3–4 prints, current S, confidence. **No predicted beat** | If confident → pre-position in Groww. Else wait; KPI is already named |
| Results / PPT / con-call | KPIs into series. Guidance {−1,0,+1} if it names the metric. Then S | Quoted KPI vs last print. Band + five-line math. Disagreement if stamp vs S > 25 |
| Order / book / rating / pledge | Only if it maps to a named KPI. Then S | Same rec format |
| Gated industry (peers) or key own-price move | News/peer x=0 unless mapped. Price = own 20d | Ping **only if S band changes** |

**Kill (store, never score, never ping):** trading window closure, ESOP allotment, newspaper publication of results, record date, book closure, RTA/registrar certs, investor complaint statements, loss/duplicate shares, compliance certs (Reg 74(5) etc.), AGM procedural notices, **AGM/EGM postal ballot**. Matched on `(category, subcategory)` unless a headline rule is named.

**Low (store, no push):** analyst meet intimations, dividend intimations, AGM agenda, routine subsidiary incorporation, RTA/secretarial role changes, **press release / media release**, **Others with empty subcategory**, **rumour verification** (headline contains “Rumour verification” or “Regulation 30(11)”). **Unknown or unmapped category → low** (stored, visible, never pushed).

**Candidate:** board meeting intimation (`Board Meeting` / `Board Meeting`), board meeting outcome, financial results, investor presentations, con-call transcripts, scheme of arrangement, `Company Update` / `General` (unless priority). **Change in Management** is candidate only if the headline or PDF title names Managing Director / MD, Chief Executive / CEO, Chief Financial / CFO, Whole-time Director, Auditor, or Resignation of Director; otherwise low.

**Priority (always notify when fresh; above candidate):** `Company Update` / `General` whose headline contains “SEBI Order”, “Adjudication”, “Show Cause”, or “Penalty”. Recency guard still applies. No digest or batching may swallow a fresh priority filing.

**Recency guard:** never notify on a filing whose `filed_at` is older than **48 hours** at poll time. Independent of an empty database and of `--notify-backfill`. Stale rows are still stored and classified.

**Collapse:** the same results print is often filed twice (`Board Meeting` / `Outcome of Board Meeting` and `Result` / `Financial Results`) within 24 hours. Store both. Notify once, preferring the Financial Results row. Set `collapsed_into` on the suppressed outcome to the results `filing_id`.

PDFs: download, `pdfplumber`. Near-empty text → `needs_manual_read`, still notify with the link, **block Buy**.

### 3. User talk-back

- “Less sure, 55, still holding” → stamp=55, note appended, S not overwritten by the stamp.
- Accept/nudge a rec → log `{S, each x_i, action}`. For post-beta weight review. Do not retune in beta.

### 4. v1 surface

- **CLI table:** name, return vs cost, last S, band, thesis, KPI series, next earnings date. `no_thesis` rows sit at the top. Thesis-less Groww holdings plus ledger `no_thesis` names count as outstanding (cache only, never the live API).
- **Local page:** `pos web` — read-only FastAPI on `127.0.0.1`. Book table and one name’s thesis / conditions / S / filings / KPI history. Delayed quotes, not a live ticker. No auth, no orders.
- **`pos sync`:** read-only Groww holdings vs ledger. Report drift and `NO_THESIS` ledger rows; do not write the ledger.
- **`pos context <TICKER>`:** local markdown dump (thesis, conditions with severity, currently touched conditions, filings, KPI history, decisions) for pasting into an external chat. No LLM call, no network. `--filings N` and `--since YYYY-MM-DD`.
- **`pos decide SYMBOL ACTION [NOTE] [--anticipatory]`:** user stamp into `decisions`. `--anticipatory` marks a decision made ahead of a results print. `pos decisions --anticipatory` lists only those.
- **`pos pack [SYMBOL] [--notify]`:** earnings pack (thesis, KPI to watch, last 3–4 prints, current S, confidence). No predicted beat. `--notify` sends the short macOS form. Without a symbol, only names with results due in the next few days.
- **macOS notification** on: earnings pack (once per due date), weekly nudge for `event`/`manual` names (once per ISO week), band change, needs_manual_read.
- **Telegram: later**, not v1.

---

## 5. Data

- **BSE primary.** Unofficial `AnnGetData` JSON; browser-like User-Agent + Referer; filter by scrip code + date.
- **NSE:** only if a holding is NSE-only.
- **Prices:** delayed public quotes (Yahoo or similar) or Groww LTP later. v1: delayed quotes + ledger qty/cost.
- **Groww holdings:** `GROWW_API_KEY` + `GROWW_API_SECRET` in `.env`. `pos sync` exchanges them (`POST /v1/token/api/access`, checksum SHA256(secret+timestamp)) for a daily access token, then `GET /v1/holdings/user`. Thin `requests` client; no growwapi SDK. Optional `GROWW_ACCESS_TOKEN` skips the exchange. Cache holdings in SQLite; CLI reads the cache.
- **LLM:** Gemini Flash (Google AI Studio). Structured JSON. Temperature 0. One call per candidate or priority filing, never per poll. Cached by filing hash. Prompt is SPEC §9 verbatim. Groq+Llama optional fallback.
- **Industry v1:** peer KPI prints from ledger names sharing `sector`. No RSS until Phase 1b.

---

## 6. Storage (SQLite)

- `tickers` / YAML ledger: mapping with `shared_conditions` and `tickers`. Each row: symbol, bse_code, nse_symbol, **status** (`held` | `exiting` | `event` | `no_thesis` | `manual`), thesis, conditions (quantitative and/or manual, each with **severity**), `conditions_include`, qty, avg_cost, confidence, sector, review_by. A blank `bse_code` loads but does not poll.
- `filings`: id, ticker, exchange, ann_id, category, subcategory, headline, pdf_url, filed_at, hash, filter_status, created_at
- `scores`: filing_id or event_id, x_kpi, x_book, x_industry, x_price, x_guidance, S, band, low_confidence, active_factors, triage_json, created_at. Inactive x is NULL, not 0. Manual conditions never activate a factor.
- `kpi_series`: ticker, kpi_name, period, value, source_filing_id
- `extractions`: filing_hash, filing_id, text, needs_manual_read, kpis_json, model, created_at. Cached by filing hash so Gemini is never re-called on a re-run.
- `alerts`: event_id, channel (macos|telegram), sent_at
- `ticker_state`: symbol, results_due, last_fetch_at, results_filed_for, pack_sent_for (ISO date of the results window already packed)
- `meta`: key/value; `nudge_week` is the ISO week already nudged
- `holdings_cache`: symbol, isin, qty, avg_cost, fetched_at (Groww snapshot; CLI reads this, never the API)
- `decisions`: ticker, date, action, note, S_at_time, **anticipatory** (user stamp / follow-or-nudge; anticipatory = ahead of a results print)
- `condition_touches`: ticker, condition_text, severity, check_kind, filing_id, touched_at. Rolling 2-quarter window for escalation.

`data/` gitignored (db + PDFs).

---

## 7. Build phases

**Phase 0 (only committed v1 scope)**

1. `config/tickers.yaml` — user fills real holdings. `held` enforces thesis + ≥1 condition at load. Other statuses load without conditions. Never auto-assign status.
2. BSE source + dedupe + SQLite.
3. Kill-list filter.
4. CLI table + delayed quotes (return vs cost).
5. macOS notify for **candidate** filings (headline + link) before LLM is on — so the pipe is testable.
6. Scheduler with the **slot / results-week / results-morning** cadence above.

Ship when: a board-meeting or results filing for a held ticker produces a macOS notification within the cadence window, and a trading-window closure does not.

**Phase 1**

- PDF extract + Gemini JSON extract of named KPIs + frozen S + rec text with arithmetic.
- Earnings pack (intimation → date → few-days-out notify).
- `decisions` log CLI (`pos decide SUZLON size_down "deliveries miss"`; optional `--anticipatory`).
- Faster poll on results morning.

**Phase 1b (later)**

- Telegram push (same events as macOS).
- Groww LTP. Holdings sync is `pos sync` (already in tree).
- Gated industry RSS.
- NSE for NSE-only names.

**Phase 2**

- Read-only local page (`pos web`, localhost). Same facts as the CLI.
- Weight review from `decisions` log after a results season. Still no ML.

---

## 8. Stack

Python 3.12, `uv`, `requests`, `pdfplumber`, `PyYAML`, SQLite stdlib, Gemini official client. Scheduler: `launchd` plist or APScheduler. Each module runnable standalone, e.g. `uv run python -m src.sources.bse SUZLON`.

```
positional-awareness/
  SPEC.md
  BUILD_PROMPT.md
  config/tickers.yaml          # user-owned; example at tickers.example.yaml
  src/sources/{base.py,bse.py}
  src/{filter.py,score.py,extract.py,notify.py,store.py,cli.py,main.py,web/}
  src/portfolio/{base.py,yaml_portfolio.py,groww.py,reconcile.py}
  data/                        # gitignored
  tests/                       # fixture JSON from a real BSE response
```

Save one real BSE response as a fixture **before** writing the filter. Filter against fixtures, not live calls.

---

## 9. Prompt guardrails (verbatim in Gemini system prompt)

- You never place a trade. You never output an action verb (including buy, sell, add, trim, hold). Report factor evidence and figures only.
- If the filing does not touch any listed KPI/condition, that factor is **inactive** (n/a), not x = 0. Do not invent a thesis.
- Numbers over adjectives. Quote figures from the filing.
- Output JSON only for extract/score calls.

---

## 10. Kill criterion (after one results season)

Keep the code if at least one real decision changed or one would-have-missed event was caught. Else keep `tickers.yaml` as a checklist and delete the loop. The ledger is the valuable part.
