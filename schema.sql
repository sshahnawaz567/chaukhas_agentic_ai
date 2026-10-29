-- ============================================================
--  Chaukas — SQLite schema  (v2: + audit trail / "who did what")
--  Portable to Postgres later: AUTOINCREMENT -> IDENTITY/SERIAL,
--  strftime(...) default -> timestamptz DEFAULT now().
--  Money is stored as INTEGER rupees. NEVER REAL for money.
-- ============================================================

PRAGMA foreign_keys = ON;

-- ============================================================
-- READ-SIDE  — Merchant 360  (seeded from data/merchants.json)
-- Context Agent reads this deterministically, keyed by id, no LLM.
-- ============================================================

-- PII legend:  [PII-1] = financial credential / strong identifier (highest)
--              [PII-2] = contact / name
-- Prototype: synthetic PII stored in plain columns (data is fake).
-- Prod: these columns are field-level ENCRYPTED at rest; keys kept separate.
-- Either way, PII is masked/tokenised at every boundary (model, logs, cache) — see B7.3.
CREATE TABLE merchants (
    merchant_id      TEXT PRIMARY KEY,                 -- "M001"  (internal id — safe, not PII)
    name             TEXT    NOT NULL,                 -- [PII-2]
    gmv_30d          INTEGER NOT NULL DEFAULT 0,        -- rupees, trailing 30 days (not PII)
    device           TEXT    CHECK (device IN ('soundbox','pos','qr','app')),
    loan_eligible    INTEGER NOT NULL DEFAULT 0,        -- 0/1 boolean
    loan_max_amount  INTEGER NOT NULL DEFAULT 0,        -- rupees
    -- --- PII columns (synthetic in prototype; encrypted at rest in prod) ---
    phone            TEXT,                              -- [PII-2]  "+9198XXXXXX10"
    vpa              TEXT,                              -- [PII-1]  UPI id  "name@okhdfc"
    pan              TEXT,                              -- [PII-1]
    account_no       TEXT,                              -- [PII-1]  bank account (payout target)
    ifsc             TEXT                               -- [PII-1]  bank branch (IFSC_MISMATCH cause lives here)
);

-- CASHFLOW FEATURE LAYER — pre-aggregated per merchant ("feature layer over
-- transactions": we store features, NOT raw transactions). Feeds the
-- deterministic loan-eligibility rule. Seeded from merchant_fixtures.json.
CREATE TABLE cashflow_features (
    merchant_id        TEXT PRIMARY KEY REFERENCES merchants(merchant_id),
    txn_count_30d      INTEGER NOT NULL DEFAULT 0,   -- total transactions, 30d
    withdrawals_30d    INTEGER NOT NULL DEFAULT 0,   -- wallet withdrawal count, 30d
    inflow_30d         INTEGER NOT NULL DEFAULT 0,   -- total credited, rupees
    outflow_30d        INTEGER NOT NULL DEFAULT 0,   -- total debited, rupees
    avg_balance        INTEGER NOT NULL DEFAULT 0,   -- avg wallet balance, rupees
    active_days_30d    INTEGER NOT NULL DEFAULT 0,   -- days with >=1 txn (0-30)
    inflow_cv          REAL    NOT NULL DEFAULT 1.0, -- inflow volatility (coeff of variation; low = steady = low risk)
    account_age_months INTEGER NOT NULL DEFAULT 0
);

-- MONEY STATE. Fetched FRESH every turn (never cached — see A7).
CREATE TABLE settlements (
    id           TEXT PRIMARY KEY,                      -- "SET-51002"
    merchant_id  TEXT    NOT NULL REFERENCES merchants(merchant_id),
    amount       INTEGER NOT NULL,                      -- rupees
    status       TEXT    NOT NULL CHECK (status IN ('success','failed','pending')),
    cause        TEXT,                                  -- "IFSC_MISMATCH" or NULL
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX idx_settlements_merchant ON settlements(merchant_id);

-- ============================================================
-- SESSIONS — one row per conversation / run. The anchor for history.
-- ============================================================
CREATE TABLE sessions (
    session_id   TEXT PRIMARY KEY,                      -- gateway-issued
    merchant_id  TEXT NOT NULL REFERENCES merchants(merchant_id),
    trace_id     TEXT NOT NULL,
    channel      TEXT CHECK (channel IN ('chat','voice','agent_desk')),
    lang         TEXT,                                  -- "hi","hinglish","en",...
    intent       TEXT,                                  -- "settlement_delay",...
    urgency      TEXT CHECK (urgency IN ('low','med','high')),
    track        TEXT CHECK (track IN ('support','sales')),
    mode         TEXT CHECK (mode IN ('autonomous','copilot','handoff')),
    outcome      TEXT CHECK (outcome IN
                   ('resolved_autonomously','needs_confirmation',
                    'handoff','resolved_by_human','failed')),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    ended_at     TEXT
);
CREATE INDEX idx_sessions_merchant ON sessions(merchant_id);

-- ============================================================
-- WRITE-SIDE — created at runtime by the Action Agent
-- ============================================================

CREATE TABLE tickets (
    id            TEXT PRIMARY KEY,                     -- "TKT-77201"
    merchant_id   TEXT NOT NULL REFERENCES merchants(merchant_id),
    session_id    TEXT,                                 -- session that raised it (soft link)
    issue         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open','in_progress','resolved','closed')),
    resolved_by   TEXT CHECK (resolved_by IN ('agent','human')),  -- NULL = still open
    resolution    TEXT,                                 -- what the fix was, human-readable
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    resolved_at   TEXT
);
CREATE INDEX idx_tickets_merchant ON tickets(merchant_id);

-- Consented loan offers = the "sales" outcome in the same conversation.
CREATE TABLE offers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id  TEXT    NOT NULL REFERENCES merchants(merchant_id),
    session_id   TEXT,
    amount       INTEGER NOT NULL,                      -- rupees
    consent      INTEGER NOT NULL DEFAULT 0,            -- 0/1; create_offer REQUIRES 1
    status       TEXT    NOT NULL DEFAULT 'offered'
                      CHECK (status IN ('offered','accepted','declined')),
    trace_id     TEXT,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ============================================================
-- TICKET_EVENTS — the human-readable activity trail.
-- "Open a ticket, see the whole story + who did each step."
-- actor answers: did the AGENT do it, or a HUMAN in the loop?
-- ============================================================
CREATE TABLE ticket_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   TEXT NOT NULL REFERENCES tickets(id),
    session_id  TEXT,                                   -- soft link
    trace_id    TEXT,
    actor       TEXT NOT NULL CHECK (actor IN ('agent','human','merchant','system')),
    actor_id    TEXT,                                   -- which agent name / which human staff id
    event_type  TEXT NOT NULL CHECK (event_type IN
                  ('created','action_taken','status_change',
                   'note','handoff','consent','resolved')),
    detail      TEXT,                                   -- human-readable or JSON
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX idx_ticket_events_ticket ON ticket_events(ticket_id, created_at);

-- ============================================================
-- AUDIT_LOG — the compliance DIFFERENTIATOR.
-- One row per money-touching DECISION: ALLOW / BLOCK / NEEDS_CONFIRMATION.
-- Doubles as the idempotency ledger. Narrow + strict (RBI / DPDP).
-- SELECT * FROM audit_log live on stage = the "wow" moment.
-- ============================================================
CREATE TABLE audit_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id           TEXT    NOT NULL,
    session_id         TEXT,                            -- ties decision back to a run
    ticket_id          TEXT,                            -- ties decision to a ticket
    ts                 TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    merchant_id        TEXT    REFERENCES merchants(merchant_id),
    actor              TEXT    NOT NULL DEFAULT 'agent'
                            CHECK (actor IN ('agent','human','system')),
    action_type        TEXT    NOT NULL,                -- "retrigger_payout", "create_offer", ...
    amount             INTEGER,                         -- rupees; NULL if non-money
    params_masked      TEXT,                            -- JSON, PII masked (NEVER raw PII)
    guardrail_decision TEXT    NOT NULL
                            CHECK (guardrail_decision IN ('ALLOW','BLOCK','NEEDS_CONFIRMATION')),
    reason             TEXT    NOT NULL,                -- "amount 32500 > auto_limit 25000"
    rollback_token     TEXT,                            -- issued BEFORE execution on ALLOW
    idempotency_key    TEXT    UNIQUE,                  -- "{session}:{step}"; NULL for blocked/non-exec
    result_ref         TEXT                             -- payout ref / ticket_id on success
);
CREATE INDEX idx_audit_trace    ON audit_log(trace_id);
CREATE INDEX idx_audit_merchant ON audit_log(merchant_id);
CREATE INDEX idx_audit_ticket   ON audit_log(ticket_id);

-- ------------------------------------------------------------
-- RECONSTRUCT A TICKET'S FULL STORY (agent + human events, in order):
--
--   SELECT created_at, actor, actor_id, event_type, detail
--   FROM   ticket_events
--   WHERE  ticket_id = 'TKT-77201'
--   ORDER  BY created_at;
--
-- And the money decisions on that same ticket:
--
--   SELECT ts, actor, action_type, amount, guardrail_decision, reason
--   FROM   audit_log
--   WHERE  ticket_id = 'TKT-77201'
--   ORDER  BY ts;
-- ------------------------------------------------------------

-- NOTES
--  * audit_log = narrow money-compliance record; ticket_events = broad
--    operational history. Two tables, two purposes, on purpose.
--  * Guardrail decision is deterministic code, never an LLM. audit_log
--    only RECORDS what that code decided.
--  * actor = how you prove "AI did this step" vs "human did this step".
