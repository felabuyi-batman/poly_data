# Polymarket Bot — Frontend Build Brief (v2, hardened)

Paste this whole file into v0 / Lovable / Cursor / Claude as the build prompt.
Sample fixtures live in `frontend/fixtures/` — use them verbatim for empty-state and dev-mode rendering.

---

## What you're building

A **read-only operations dashboard** for a Polymarket trading bot. The bot runs as a cron job on a VPS and writes JSON files to `bot/state/`. The dashboard reads those files and a few CLOB endpoints, and visualizes them.

**Single operator. Self-hosted. No multi-tenancy. No order placement UI.** The only mutation is a kill switch.

## Tech stack (non-negotiable)

- **Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui**
- **Recharts** for charts
- **SWR** for client polling (default 30s; configurable via env)
- **Node runtime** for all route handlers (we read local files; *not* Edge)
- **No database.** State is on disk.

## Deployment topology — pick ONE, brief assumes (1)

1. **Co-located on the same VPS as the bot** (RECOMMENDED)
   - Next.js runs in `output: "standalone"` mode behind Caddy
   - Reads `bot/state/*.json` directly off the local disk
   - Caddy provides HTTPS + Basic Auth (one-line config)
   - This is the only deployment path that supports log tail and instant kill switch.

2. **Split: bot on VPS, frontend on Vercel**
   - VPS runs a 40-line FastAPI sidecar (`bot/api_server.py`, scaffolded at the bottom of this brief) exposing the same endpoints over HTTPS+Basic Auth.
   - Vercel app proxies through. All `/api/state/*` routes work unchanged because they're file-readers; for split mode swap the implementation to `fetch(BOT_API_URL+...)`.

We default to mode 1. See "Split deployment" at the bottom for mode 2.

## Data sources

### Files written by the bot
| File | Update cadence | Freshness budget |
|---|---|---|
| `state/targets.json` | weekly via `bot.targets` | 10 days |
| `state/queue.json`   | every 15min via `bot.scanner` | 1 hour |
| `state/theses.json`  | every 15min via `bot.brain` | 2 hours (often empty by design) |
| `state/positions.json` | every 15min via `bot.executor` + every 5min via `bot.exit_monitor` | 30 minutes |
| `state/cron.log`     | continuous | 30 minutes |
| `state/HALT`         | created/removed by frontend | n/a |

**Each file gets its own freshness threshold** — don't use one number.

### Live data the bot does NOT write (frontend fetches directly)
| Endpoint | Purpose | Cache |
|---|---|---|
| `GET https://clob.polymarket.com/midpoint?token_id=…` | current YES price per open position, for unrealized P&L | 30s, server-side |

This is the **only** external call the frontend makes. No auth needed.

## JSON schemas (the contract — fixtures match exactly)

### `state/targets.json`
```json
[{"wallet":"0xabc","trades":142,"wins":103,"win_rate":0.725,"total_pnl":18420.55,"markets_traded":67}]
```

### `state/queue.json`
```json
[{"market_id":"0x...","condition_id":"0x...","question":"...","slug":"...","category":"crypto","midpoint":0.62,"estimate":0.74,"gap":0.12,"bid_depth":1240.5,"ask_depth":980.2,"hours":84.5,"volume":245000,"yes_token":"123","no_token":"456","ev":0.27}]
```
`ev` = `gap * min(bid_depth, ask_depth) * 0.001` (default sort key). Sports markets are pre-filtered server-side via `SCAN_CATEGORY_BLACKLIST` and will not appear here.

### `state/theses.json`
```json
[{"market_id":"0x...","question":"...","yes_token":"123","no_token":"456","category":"crypto","midpoint":0.62,"decision":{"action":"BUY_YES","confidence":0.81,"p_win":0.81,"price_at_decision":0.62,"agreeing_checks":["..."]},"size_usd":42.50,"checks":[{"signal":"BUY_YES","confidence":0.78,"note":"..."}]}]
```

### `state/positions.json`
```json
[{"market_id":"0x...","question":"...","side":"BUY_YES","entry_price":0.62,"target_price":0.92,"size_usd":42.50,"votes":[{"action":"BUY_YES","confidence":0.78}],"order":{"client_id":"abc","token":"123","price":0.62,"size_usd":42.50,"size_shares":68.55,"side":"BUY","status":"live-cli"},"status":"OPEN","opened_at":"2026-04-23T14:22:00+00:00","exit_reason":null,"exit_price":null,"closed_at":null,"realized_pnl":null}]
```

`status` ∈ `{OPEN, CLOSED, FAILED}`. When CLOSED: `exit_reason ∈ {TARGET_HIT, VOLUME_EXIT, STALE_THESIS}` and `realized_pnl` is a number.

## Critical robustness rules (these caused real bugs in v1)

1. **Atomic-read every JSON file** with retry on parse failure:
   ```ts
   // lib/safe-read.ts
   export async function safeReadJson<T>(path: string, fallback: T) {
     for (let i = 0; i < 2; i++) {
       try {
         const stat = await fs.stat(path);
         const text = await fs.readFile(path, "utf8");
         return { data: JSON.parse(text) as T, error: null, mtime: stat.mtime };
       } catch (e: any) {
         if (e.code === "ENOENT") return { data: fallback, error: "file-missing", mtime: null };
         if (i === 0) await new Promise(r => setTimeout(r, 250));
         else return { data: fallback, error: String(e.message ?? e), mtime: null };
       }
     }
     return { data: fallback, error: "unreachable", mtime: null };
   }
   ```
   **Every state-file route uses this.** Never throw 500 from a state route — return `{data: fallback, stale: true, error: "..."}`.

2. **Per-file freshness.** Use the table above. `<StaleBanner file="positions" />` reads `mtime` and the file's budget; banner color: green (fresh) → amber (≥budget) → red (≥2× budget).

3. **No "current price" without graceful fallback.** If the CLOB midpoint call fails, show entry price greyed out with tooltip "live price unavailable" — never crash, never show NaN.

4. **Empty states everywhere.** Each list page must render with zero data:
   - `/queue` empty: "No markets passed scanner filters. Last run: 12 minutes ago."
   - `/theses` empty: "No theses meet the 0.75 confidence + 3-check threshold. This is normal — the bot is selective."
   - `/positions` empty: "No positions yet. Last executor run: 3 minutes ago."
   - `/wallets` empty: "Run `uv run python -m bot.targets` to populate."

5. **No spinners on cards.** Use shadcn `Skeleton` rows.

6. **Activity feed is derived, not stored.** The bot writes no event log. Compute the feed by:
   - For each position: emit `{type:"OPENED", at: opened_at, ...}`
   - If closed: also emit `{type:"CLOSED", at: closed_at, reason, pnl, ...}`
   - Sort merged by `at` desc, take 20.

7. **Equity curve guard.** With `<5` CLOSED positions show a "P&L breakdown" bar chart (`TARGET_HIT vs VOLUME_EXIT vs STALE_THESIS`, $ realized) instead of a line chart. Switch to line ≥5 closed.

## Pages

### `/` — Overview
**Stat cards (top row):**
1. **Bankroll** — `BANKROLL_USD` env, big number
2. **Open positions** — count + total `size_usd`
3. **Realized P&L (today)** — `Σ realized_pnl WHERE closed_at = today`, color
4. **Realized P&L (all-time)** — `Σ realized_pnl WHERE status='CLOSED'`
5. **Win rate** — `wins / closed_count`
6. **Bot status** — derived from per-file freshness; green if ALL files within budget

**Body (two columns on desktop, stacked on mobile):**
- Left: **Open positions table** — question | side | entry | current* | size | age | unreal P&L
  - `*` current = CLOB midpoint, fetched server-side, 30s cache
  - Unreal P&L = `size_shares * (current - entry)` for BUY_YES, mirrored for BUY_NO
- Right: **Activity feed** (derived per rule #6)

**Bottom:** Equity curve OR breakdown bar (per rule #7)

### `/queue`
Sortable table of `queue.json`:
question (truncate, ext-link to `https://polymarket.com/event/{slug}`) | category | midpoint | estimate | gap (green ≥ 0.07) | **ev (default sort desc)** | bid+ask depth | hours | volume.
Filter chips: category, hours-bucket (`<24h`, `24-72h`, `72h+`).

### `/theses`
Cards (not table). Each card:
- Question (h3), category badge, `$X.XX` size badge
- Decision: action pill (BUY_YES green / BUY_NO red), confidence as progress bar
- 4 check rows: signal pill + note + confidence number
- Mini horizontal bar visualizing `midpoint` vs `p_win` (the edge)

### `/positions`
Tabs: **Open** | **Closed** | **Failed** | **All**
Closed columns add: exit_reason badge, exit_price, realized_pnl color, duration.
Click row → modal with full thesis (votes, checks, order JSON pretty-printed, `client_id`).

### `/wallets`
Table: rank, wallet (link to `https://polygonscan.com/address/{addr}`), trades, win_rate (progress), total_pnl color, markets_traded.

### `/control`
- **HALT toggle** (the ONLY mutation in this app)
- **Per-file freshness grid** — 4 boxes, one per state file, mtime + budget + status
- **Log tail** — last 200 lines of `cron.log`, mono font, auto-scroll bottom, search box
- **Config view** — read-only, safe subset only:
  ```
  BANKROLL_USD, DRY_RUN, KELLY_MAX_FRACTION, BRAIN_MIN_CONFIDENCE,
  BRAIN_MIN_CHECKS_AGREEING, SCAN_MIN_GAP, MIN_MARKET_VOLUME_USD,
  EXIT_TARGET_PCT, EXIT_VOLUME_SPIKE_MULT, EXIT_STALE_HOURS
  ```
  **Never expose**: `OPENAI_API_KEY`, `POLY_PRIVATE_KEY`, `POLY_FUNDER_ADDRESS`, anything matching `/key|secret|token|password|private/i`. The route filter in `app/api/config/route.ts` is the choke point.

## API routes

```
GET  /api/state/targets    → SafeRead<Target[]>
GET  /api/state/queue      → SafeRead<QueueItem[]>
GET  /api/state/theses     → SafeRead<Thesis[]>
GET  /api/state/positions  → SafeRead<Position[]>
GET  /api/state/meta       → { mtimes, halt: boolean, budgets }
GET  /api/state/log?n=200  → text
GET  /api/config           → safe subset
GET  /api/midpoints?tokens=t1,t2,t3 → { [token]: number | null }   // 30s server cache
POST /api/halt             → body: {enabled: boolean}              // requires HALT_TOKEN header
```

`SafeRead<T>` shape: `{ data: T, mtime: string | null, stale: boolean, error: string | null }`.

All read endpoints: `export const dynamic = "force-dynamic"; export const revalidate = 0;` and `Cache-Control: no-store`. SWR refresh: `NEXT_PUBLIC_REFRESH_MS` (default 30000).

### Auth (only on the mutation)
`POST /api/halt` requires header `x-halt-token: $HALT_TOKEN`. The frontend reads `HALT_TOKEN` from a server-only env, attaches it via a server action, and never exposes it to the client. **Without `HALT_TOKEN` set the route returns 503**, so a misconfigured deploy fails closed.

For the rest of the app, put **Caddy Basic Auth** in front (mode 1) or **Vercel Password Protection / Cloudflare Access** (mode 2). The brief assumes a perimeter; per-route auth would be overkill for a single-operator tool.

## Visual design

- **Dark mode default**, light toggle in header
- shadcn defaults; collapsible sidebar nav
- Color tokens: green `#10b981` BUY_YES/profit, red `#ef4444` BUY_NO/loss/HALT, amber `#f59e0b` stale/warning, slate `#64748b` neutral/closed-flat
- Numbers `font-mono`, prices `0.00`, money `$X,XXX.XX`
- All times user-local with UTC on hover (`title="2026-04-23T14:22:00Z"`)
- Mobile <768px: tables collapse to cards

## File layout to generate

```
frontend/
├── app/
│   ├── layout.tsx
│   ├── globals.css
│   ├── page.tsx
│   ├── queue/page.tsx
│   ├── theses/page.tsx
│   ├── positions/page.tsx
│   ├── wallets/page.tsx
│   ├── control/page.tsx
│   └── api/
│       ├── state/[file]/route.ts
│       ├── state/meta/route.ts
│       ├── state/log/route.ts
│       ├── config/route.ts
│       ├── midpoints/route.ts
│       └── halt/route.ts
├── components/
│   ├── nav.tsx
│   ├── stat-card.tsx
│   ├── positions-table.tsx
│   ├── thesis-card.tsx
│   ├── equity-chart.tsx
│   ├── pnl-breakdown.tsx
│   ├── side-badge.tsx
│   ├── stale-banner.tsx
│   ├── halt-banner.tsx
│   └── ui/...
├── lib/
│   ├── safe-read.ts
│   ├── state-client.ts        # SWR hooks
│   ├── format.ts              # money / pct / duration / age
│   ├── midpoint-cache.ts      # 30s LRU on the server
│   ├── activity.ts            # derive feed from positions[]
│   └── types.ts
├── fixtures/                  # ← copied from /frontend/fixtures
│   ├── targets.json
│   ├── queue.json
│   ├── theses.json
│   └── positions.json
├── Caddyfile.example
├── Dockerfile
├── docker-compose.example.yml
├── next.config.js             # output: "standalone"
├── .env.example
└── README.md
```

`.env.example`:
```
# REQUIRED
BOT_STATE_DIR=/srv/poly_data/bot/state
BOT_LOG_FILE=/srv/poly_data/bot/state/cron.log
BANKROLL_USD=200
HALT_TOKEN=                   # generate: openssl rand -hex 32

# OPTIONAL
NEXT_PUBLIC_REFRESH_MS=30000
CLOB_BASE_URL=https://clob.polymarket.com

# SPLIT MODE ONLY (mode 2)
# BOT_API_URL=https://bot.example.com
# BOT_API_USER=admin
# BOT_API_PASS=...
```

## TypeScript types

```ts
export type Side = "BUY_YES" | "BUY_NO";
export type CheckSignal = "BUY_YES" | "BUY_NO" | "NEUTRAL";
export type PositionStatus = "OPEN" | "CLOSED" | "FAILED";
export type ExitReason = "TARGET_HIT" | "VOLUME_EXIT" | "STALE_THESIS";
export type OrderStatus = "paper" | "live-cli" | "live-agents" | "error";

export interface SafeRead<T> { data: T; mtime: string | null; stale: boolean; error: string | null; }

export interface Target { wallet: string; trades: number; wins: number; win_rate: number; total_pnl: number; markets_traded: number; }
export interface QueueItem { market_id: string; condition_id: string; question: string; slug: string; category: string; midpoint: number; estimate: number | null; gap: number | null; bid_depth: number; ask_depth: number; hours: number; volume: number; yes_token: string; no_token: string | null; ev: number; }
export interface Check { signal: CheckSignal; confidence: number; note: string; }
export interface Decision { action: Side; confidence: number; p_win: number; price_at_decision: number; agreeing_checks: string[]; }
export interface Thesis { market_id: string; question: string; yes_token: string; no_token: string | null; category: string; midpoint: number; decision: Decision; size_usd: number; checks: Check[]; }
export interface Vote { action: Side | "HOLD"; confidence: number; agent?: string; }
export interface Order { client_id: string; token: string; price: number; size_usd: number; size_shares: number; side: "BUY"; status: OrderStatus; reason?: string; }
export interface Position { market_id: string; question: string; side: Side; entry_price: number; target_price: number; size_usd: number; votes: Vote[]; order: Order; status: PositionStatus; opened_at: string; exit_reason: ExitReason | null; exit_price: number | null; closed_at: string | null; realized_pnl: number | null; }

export type ActivityEvent =
  | { type: "OPENED"; at: string; question: string; side: Side; size_usd: number; market_id: string }
  | { type: "CLOSED"; at: string; question: string; reason: ExitReason; pnl: number; market_id: string };
```

## Acceptance criteria (verify all)

- [ ] All 6 pages render correctly with the provided `fixtures/*.json`
- [ ] All 6 pages render correctly with state files **missing** (empty-state copy from rule #4)
- [ ] All 6 pages render correctly with state files **mid-write** (corrupt JSON → safe fallback, stale banner)
- [ ] Per-file stale banners use the correct budget per the table
- [ ] Activity feed derives correctly from positions, no separate event log assumed
- [ ] Equity chart switches to breakdown when `<5` closed
- [ ] Open positions show CLOB midpoint with graceful fallback
- [ ] `POST /api/halt` 401s without `x-halt-token`, 503s without `HALT_TOKEN` env
- [ ] `/api/config` never returns any key matching `/key|secret|token|password|private/i`
- [ ] Mobile layout passes at 375px wide; all tables collapse to cards
- [ ] No client-side fetches of secrets; check Network tab in dev tools
- [ ] `next build` works in `output: "standalone"` mode

## Out of scope

- Auth on read routes (use Caddy/Vercel/Cloudflare in front)
- Order placement
- Editing config
- Per-market historical charts
- Notifications (separate cron)

---

## Split deployment (mode 2) — only if you must

Replace `app/api/state/[file]/route.ts` with a thin proxy:

```ts
const r = await fetch(`${process.env.BOT_API_URL}/state/${params.file}`, {
  headers: { Authorization: "Basic " + Buffer.from(`${process.env.BOT_API_USER}:${process.env.BOT_API_PASS}`).toString("base64") },
  cache: "no-store",
});
return new Response(r.body, { status: r.status, headers: { "Cache-Control": "no-store" } });
```

VPS-side, run this 40-line FastAPI sidecar (committed as `bot/api_server.py`):

```python
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pathlib import Path
import os, json, secrets

app = FastAPI()
sec = HTTPBasic()
STATE = Path(os.environ["BOT_STATE_DIR"])
USER = os.environ["BOT_API_USER"]; PW = os.environ["BOT_API_PASS"]
HALT_TOKEN = os.environ.get("HALT_TOKEN", "")

def auth(c: HTTPBasicCredentials = Depends(sec)):
    if not (secrets.compare_digest(c.username, USER) and secrets.compare_digest(c.password, PW)):
        raise HTTPException(401)

@app.get("/state/{name}")
def state(name: str, _=Depends(auth)):
    if name not in {"targets","queue","theses","positions"}: raise HTTPException(404)
    p = STATE / f"{name}.json"
    if not p.exists(): return {"data": [], "mtime": None, "stale": True, "error": "missing"}
    return {"data": json.loads(p.read_text()), "mtime": p.stat().st_mtime, "stale": False, "error": None}

@app.post("/halt")
def halt(enabled: bool, x_halt_token: str = "", _=Depends(auth)):
    if not HALT_TOKEN or not secrets.compare_digest(x_halt_token, HALT_TOKEN): raise HTTPException(401)
    f = STATE / "HALT"
    if enabled: f.write_text("halted")
    elif f.exists(): f.unlink()
    return {"halt": f.exists()}
```

Run with: `uvicorn bot.api_server:app --host 127.0.0.1 --port 8787` behind Caddy.

---

**Build this. Use shadcn defaults. Use the fixtures. Don't add features not on this brief.**
