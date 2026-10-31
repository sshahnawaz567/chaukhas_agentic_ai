-- ============================================================
--  Chaukas — SQLite schema  (v3.2: + CONSENT_WITHDRAWN, consents DELETE trigger; v3.1: + consents, KFS on offers, ACTION_DISABLED;
--  v3: + turns / handoffs / executions,
--  append-only audit, cause-aware settlements, daily limit support)
--  Portable to Postgres later: AUTOINCREMENT -> IDENTITY/SERIAL,
--  strftime(...) default -> timestamptz DEFAULT now(),
--  triggers -> plpgsql triggers / REVOKE UPDATE,DELETE.
--
--  CONVENTIONS (frozen — all 3 members follow these)
--   * Money      : INTEGER rupees. NEVER REAL for money.
--   * Timestamps : TEXT, ISO-8601 UTC  "2026-10-31T09:15:00Z".
--   * Lang codes : BCP-47 as used by Sarvam  "hi-IN","en-IN","ta-IN",...
--   * IDs        : merchant "M001", settlement "SET-xxxxx", ticket "TKT-xxxxx",
--                  offer "OFF-xxxxx", handoff "HO-xxxxx",
--                  idempotency_key "{session_id}:{step_no}".
--   * PRAGMA foreign_keys is PER CONNECTION — set it on every connect().
--   * Source of truth for structure = this file. merchant_fixtures.json is
--     only seed data (loaded by data/seed.py).
-- ============================================================

PRAGMA foreign_keys = ON;

-- ============================================================
-- READ-SIDE — Merchant 360  (seeded from data/merchant_fixtures.json)
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
    gmv_30d          INTEGER NOT NULL DEFAULT 0,       -- rupees, GROSS sales value, 30d (not PII)
    device           TEXT    CHECK (device IN ('soundbox','pos','qr','app')),
    preferred_lang   TEXT    NOT NULL DEFAULT 'hi-IN',
    kyc_status       TEXT    NOT NULL DEFAULT 'verified'
                          CHECK (kyc_status IN ('verified','pending','rejected')),
    -- When the merchant last corrected bank details. If this is AFTER a
    -- settlement failed with IFSC_MISMATCH, a retrigger is valid; else it
    -- would just fail again -> ask merchant to update details / handoff.
    bank_details_updated_at TEXT,
    -- --- PII columns (synthetic in prototype; encrypted at rest in prod) ---
    phone            TEXT,                             -- [PII-2]  "+919800000001"
    vpa              TEXT,                             -- [PII-1]  UPI id  "name@paytm"
    pan              TEXT,                             -- [PII-1]
    account_no       TEXT,                             -- [PII-1]  bank account (payout target)
    ifsc             TEXT                              -- [PII-1]  bank branch
);
-- NOTE: loan eligibility is NOT stored here. It comes from the SIMULATED
-- LENDER integrations/lending.check_eligibility() -> {eligible, max_amount,
-- reason_codes}, computed from cashflow_features with placeholder thresholds
-- in config/lender_sim.yaml. In prod the regulated lender decides this;
-- Chaukas only consumes it. One source, no drift.

-- CASHFLOW FEATURE LAYER — pre-aggregated per merchant ("feature layer over
-- transactions": we store features, NOT raw transactions).
-- Feeds the deterministic loan-eligibility rule.
CREATE TABLE cashflow_features (
    merchant_id        TEXT PRIMARY KEY REFERENCES merchants(merchant_id),
    txn_count_30d      INTEGER NOT NULL DEFAULT 0,   -- total transactions, 30d
    withdrawals_30d    INTEGER NOT NULL DEFAULT 0,   -- wallet withdrawal count, 30d
    inflow_30d         INTEGER NOT NULL DEFAULT 0,   -- NET credited after refunds/MDR/holds, rupees
    outflow_30d        INTEGER NOT NULL DEFAULT 0,   -- total debited, rupees
    avg_balance        INTEGER NOT NULL DEFAULT 0,   -- avg wallet balance, rupees
    active_days_30d    INTEGER NOT NULL DEFAULT 0,   -- days with >=1 txn (0-30)
    inflow_cv          REAL    NOT NULL DEFAULT 1.0, -- inflow volatility (coeff of variation; low = steady = low risk)
    account_age_months INTEGER NOT NULL DEFAULT 0
);

-- MONEY STATE. Fetched FRESH every turn (never cached — see A7).
CREATE TABLE settlements (
    id               TEXT PRIMARY KEY,                  -- "SET-99213"
    merchant_id      TEXT    NOT NULL REFERENCES merchants(merchant_id),
    amount           INTEGER NOT NULL CHECK (amount > 0),  -- rupees
    settlement_date  TEXT    NOT NULL,                  -- business date the payout was due ("pichle hafte ka paisa")
    status           TEXT    NOT NULL
                          CHECK (status IN ('success','failed','pending','retriggered')),
    -- Cause drives the PLAN (see plan templates):
    --   IFSC_MISMATCH -> retrigger only if bank_details_updated_at > failure; else ask/handoff
    --   BANK_DOWN     -> failed: retrigger ok | pending: do NOT retrigger, give ETA
    --   KYC_PENDING   -> never retrigger; send KYC link + handoff
    cause            TEXT CHECK (cause IN ('IFSC_MISMATCH','BANK_DOWN','KYC_PENDING')),
    retry_count      INTEGER NOT NULL DEFAULT 0,
    payout_ref       TEXT,                              -- set by retrigger_payout on success
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    CHECK (status <> 'success' OR cause IS NULL)
);
CREATE INDEX idx_settlements_merchant ON settlements(merchant_id, settlement_date);

-- ============================================================
-- SESSIONS + TURNS — conversation anchor and history (multi-turn consent)
-- ============================================================
CREATE TABLE sessions (
    session_id        TEXT PRIMARY KEY,                 -- gateway-issued
    merchant_id       TEXT NOT NULL REFERENCES merchants(merchant_id),
    channel           TEXT CHECK (channel IN ('chat','voice','agent_desk')),
    mode              TEXT CHECK (mode IN ('autonomous','copilot')),
    lang              TEXT,                             -- latest detected, "hi-IN"
    intent            TEXT,                             -- latest intent, "settlement_delay"
    urgency           TEXT CHECK (urgency IN ('low','med','high')),
    track             TEXT CHECK (track IN ('support','sales')),
    -- A step waiting for merchant/human confirmation (serialised PlannedStep).
    -- Next turn "haan bhejo" resumes THIS step -> guardrail re-checks it.
    pending_step_json TEXT,
    pending_audit_id  INTEGER REFERENCES audit_log(id), -- the NEEDS_CONFIRMATION row
    outcome           TEXT CHECK (outcome IN
                        ('resolved_autonomously','needs_confirmation',
                         'handoff','resolved_by_human','failed')),
    -- Proactive feature: who started this session. Server-set only (event watcher); the guardrail reads it
    -- fresh from here, never from request bodies. 'proactive' => money actions always need a yes.
    trigger_source    TEXT NOT NULL DEFAULT 'merchant' CHECK (trigger_source IN ('merchant','proactive')),
    trigger_ref       TEXT,                             -- e.g. 'settlement_failed:SET-99213' (dedupe key)
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    ended_at          TEXT
);
CREATE INDEX idx_sessions_merchant ON sessions(merchant_id);

-- One row per message. trace_id is PER TURN (one run of the loop).
CREATE TABLE turns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL REFERENCES sessions(session_id),
    turn_no      INTEGER NOT NULL,
    trace_id     TEXT    NOT NULL,
    role         TEXT    NOT NULL CHECK (role IN ('merchant','agent','human')),
    text_masked  TEXT    NOT NULL,                      -- PII masked, NEVER raw
    lang         TEXT,
    intent       TEXT,                                  -- for merchant turns
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (session_id, turn_no)
);

-- ============================================================
-- WRITE-SIDE — created at runtime by the Action / Handoff agents
-- ============================================================

CREATE TABLE tickets (
    id            TEXT PRIMARY KEY,                     -- "TKT-77201"
    merchant_id   TEXT NOT NULL REFERENCES merchants(merchant_id),
    settlement_id TEXT REFERENCES settlements(id),      -- lets agent UPDATE existing ticket instead of raising a duplicate
    session_id    TEXT,                                 -- session that raised it (soft link; NULL for seeded)
    issue         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open','in_progress','resolved','closed')),
    resolved_by   TEXT CHECK (resolved_by IN ('agent','human')),  -- NULL = still open
    resolution    TEXT,                                 -- what the fix was, human-readable
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    resolved_at   TEXT
);
CREATE INDEX idx_tickets_merchant   ON tickets(merchant_id);
CREATE INDEX idx_tickets_settlement ON tickets(settlement_id);

-- Loan offers = the "sales" outcome in the same conversation.
-- Lifecycle: offered (consent=0) -> accepted (consent=1) | declined | expired
CREATE TABLE offers (
    id           TEXT PRIMARY KEY,                      -- "OFF-10001"
    merchant_id  TEXT    NOT NULL REFERENCES merchants(merchant_id),
    session_id   TEXT,
    trace_id     TEXT,
    amount       INTEGER NOT NULL CHECK (amount > 0),   -- rupees, <= derived max_amount
    consent      INTEGER NOT NULL DEFAULT 0 CHECK (consent IN (0,1)),
    consent_at   TEXT,
    declined_at  TEXT,                                  -- drives OFFER_COOLING_OFF
    lender_name  TEXT,                                  -- regulated entity making the offer (RBI digital lending: disclose the lender)
    kfs_json     TEXT,                                  -- Key Fact Statement shown BEFORE consent: {apr_pct, processing_fee_inr, tenure_months, total_repayable_inr, grievance_contact} [MOCK values]
    kfs_shown_at TEXT,                                  -- consent is only valid if KFS was shown first
    status       TEXT    NOT NULL DEFAULT 'offered'
                      CHECK (status IN ('offered','accepted','declined','expired')),
    expires_at   TEXT,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    CHECK (status <> 'accepted' OR (consent = 1 AND consent_at IS NOT NULL)),
    CHECK (status <> 'declined' OR declined_at IS NOT NULL),
    CHECK (status <> 'accepted' OR kfs_shown_at IS NOT NULL)
);
CREATE INDEX idx_offers_merchant ON offers(merchant_id, status);

-- Human-in-the-loop queue. Agent-desk (Mode 2) reads THIS table.
-- A structured decision brief — never a transcript.
CREATE TABLE handoffs (
    id               TEXT PRIMARY KEY,                  -- "HO-00001"
    session_id       TEXT NOT NULL REFERENCES sessions(session_id),
    merchant_id      TEXT NOT NULL REFERENCES merchants(merchant_id),
    ticket_id        TEXT REFERENCES tickets(id),
    trace_id         TEXT NOT NULL,
    reason_code      TEXT NOT NULL,                     -- same enum as audit_log.reason_code, or LOW_CONFIDENCE / UNKNOWN_INTENT / OUT_OF_SCOPE
    brief_json       TEXT NOT NULL,                     -- HandoffBrief {asked, verified, done[], refused[], reason, confidence, decision_needed} — masked
    confidence       REAL CHECK (confidence BETWEEN 0 AND 1),
    decision_needed  TEXT NOT NULL,                     -- the ONE decision the human must make
    status           TEXT NOT NULL DEFAULT 'open'
                          CHECK (status IN ('open','claimed','resolved')),
    assigned_to      TEXT,                              -- staff id
    human_decision   TEXT,                              -- what the human chose
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    resolved_at      TEXT
);
CREATE INDEX idx_handoffs_status ON handoffs(status, created_at);

-- ============================================================
-- CONSENTS — DPDP Act 2023 consent artefacts (append-only history).
-- One row per grant or withdrawal, per purpose. Latest row per
-- (merchant_id, purpose) = current state. Withdrawal is as easy as grant.
-- ============================================================
CREATE TABLE consents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id    TEXT NOT NULL REFERENCES merchants(merchant_id),
    purpose        TEXT NOT NULL CHECK (purpose IN ('ai_assistance','loan_offer')),
    action         TEXT NOT NULL CHECK (action IN ('granted','withdrawn')),
    notice_version TEXT NOT NULL,                      -- which notice text the merchant saw (compliance/disclosure.py)
    channel        TEXT,                               -- chat / voice / agent_desk
    session_id     TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX idx_consents_merchant ON consents(merchant_id, purpose, created_at);

CREATE TRIGGER consents_append_only BEFORE UPDATE ON consents
BEGIN SELECT RAISE(ABORT, 'consents is append-only — insert a withdrawn row instead'); END;

CREATE TRIGGER consents_no_delete BEFORE DELETE ON consents
BEGIN SELECT RAISE(ABORT, 'consents is append-only — insert a withdrawn row instead'); END;

-- ============================================================
-- TICKET_EVENTS — the human-readable activity trail (append-only).
-- "Open a ticket, see the whole story + who did each step."
-- ============================================================
CREATE TABLE ticket_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   TEXT NOT NULL REFERENCES tickets(id),
    session_id  TEXT,                                   -- soft link
    trace_id    TEXT,
    actor       TEXT NOT NULL CHECK (actor IN ('agent','human','merchant','system')),
    actor_id    TEXT,                                   -- which agent name / which staff id
    event_type  TEXT NOT NULL CHECK (event_type IN
                  ('created','action_taken','status_change',
                   'note','handoff','consent','resolved')),
    detail      TEXT,                                   -- human-readable or JSON (masked)
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX idx_ticket_events_ticket ON ticket_events(ticket_id, created_at);

-- ============================================================
-- AUDIT_LOG — the compliance DIFFERENTIATOR. APPEND-ONLY (enforced by trigger).
-- One row per money/consent DECISION: ALLOW / BLOCK / NEEDS_CONFIRMATION.
-- It records WHAT THE DETERMINISTIC GUARDRAIL DECIDED — never an LLM.
-- Execution outcome is NOT written here (that would need an UPDATE) —
-- it lives in `executions`.
-- ============================================================
CREATE TABLE audit_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id           TEXT    NOT NULL,
    session_id         TEXT,
    ticket_id          TEXT,
    ts                 TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    merchant_id        TEXT    REFERENCES merchants(merchant_id),
    -- who caused this decision: agent (autonomous), merchant (gave consent),
    -- human (copilot approved), system (scheduled/replay)
    actor              TEXT    NOT NULL DEFAULT 'agent'
                            CHECK (actor IN ('agent','merchant','human','system')),
    step_no            INTEGER,                         -- position in the plan
    action_type        TEXT    NOT NULL,                -- "retrigger_payout", "create_offer", ...
    amount             INTEGER,                         -- rupees; NULL if non-money
    params_masked      TEXT,                            -- JSON, PII masked (NEVER raw PII)
    guardrail_decision TEXT    NOT NULL
                            CHECK (guardrail_decision IN ('ALLOW','BLOCK','NEEDS_CONFIRMATION')),
    reason_code        TEXT    NOT NULL CHECK (reason_code IN (
                         'WITHIN_POLICY',            -- ALLOW
                         'CONFIRMED_BY_MERCHANT',    -- ALLOW after step-up / consent
                         'APPROVED_BY_HUMAN',        -- ALLOW from copilot
                         'NOT_IN_ALLOW_LIST',        -- BLOCK
                         'ACTION_DISABLED',          -- BLOCK (kill switch: policy.yaml disabled_actions)
                         'NEVER_ALLOWED',            -- BLOCK (e.g. debit_merchant_account)
                         'INVALID_PARAMS',           -- BLOCK (schema validation failed)
                         'LEDGER_MISMATCH',          -- BLOCK (amount/id doesn't match fresh ledger)
                         'NOT_RETRIGGERABLE',        -- BLOCK (settlement not failed / cause forbids)
                         'DUPLICATE_ACTION',         -- BLOCK (idempotency key already executed)
                         'OVER_AUTO_LIMIT',          -- NEEDS_CONFIRMATION (amount > auto_limit)
                         'OVER_DAILY_LIMIT',         -- NEEDS_CONFIRMATION (today_total + amount > daily limit)
                         'CONSENT_REQUIRED',         -- NEEDS_CONFIRMATION (sales offer / irreversible)
                         -- offer gating (create_offer) — guardrail decides WHETHER/WHEN to offer
                         'OFFER_NOT_ELIGIBLE',       -- BLOCK (simulated lender said not eligible)
                         'ISSUE_UNRESOLVED',         -- BLOCK (support issue not actioned / handoff open / KYC pending)
                         'OFFER_COOLING_OFF',        -- BLOCK (merchant declined an offer within cooling-off window)
                         'CONSENT_WITHDRAWN'         -- BLOCK (merchant withdrew loan_offer consent; DPDP s.6)
                       )),
    reason             TEXT    NOT NULL,                -- human-readable: "amount 32500 > auto_limit 25000"
    rollback_token     TEXT,                            -- issued BEFORE execution, only on ALLOW
    confirms_audit_id  INTEGER REFERENCES audit_log(id) -- ALLOW row that resolves an earlier NEEDS_CONFIRMATION row
);
CREATE INDEX idx_audit_trace    ON audit_log(trace_id);
CREATE INDEX idx_audit_merchant ON audit_log(merchant_id, ts);
CREATE INDEX idx_audit_ticket   ON audit_log(ticket_id);

CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

-- ============================================================
-- EXECUTIONS — idempotency ledger + execution state (mutable).
-- Exactly one row per ALLOWed action that was actually executed.
-- Status: pending -> success | failed ;  success -> rolled_back
-- ============================================================
CREATE TABLE executions (
    idempotency_key  TEXT PRIMARY KEY,                  -- "{session_id}:{step_no}" — 2nd call returns 1st result
    audit_id         INTEGER NOT NULL UNIQUE REFERENCES audit_log(id),
    trace_id         TEXT    NOT NULL,
    session_id       TEXT,
    merchant_id      TEXT    NOT NULL REFERENCES merchants(merchant_id),
    action_type      TEXT    NOT NULL,
    amount           INTEGER,                           -- rupees; counted for daily limit
    rollback_token   TEXT    NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending','success','failed','rolled_back')),
    result_ref       TEXT,                              -- payout_ref / ticket_id / offer_id
    error            TEXT,                              -- masked error message on failure
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX idx_exec_merchant_day ON executions(merchant_id, created_at);

-- Defense in depth: the DATABASE itself refuses to record an execution
-- unless the linked audit decision is ALLOW. The orchestrator invariant
-- ("guardrail before action") is enforced in code AND here.
CREATE TRIGGER executions_require_allow BEFORE INSERT ON executions
WHEN (SELECT guardrail_decision FROM audit_log WHERE id = NEW.audit_id) IS NOT 'ALLOW'
BEGIN SELECT RAISE(ABORT, 'execution requires an ALLOW decision in audit_log'); END;

-- ------------------------------------------------------------
-- USEFUL QUERIES
--
-- Daily cumulative limit (Guardrail check; money-moving actions only):
--   SELECT COALESCE(SUM(amount),0) FROM executions
--   WHERE  merchant_id = ? AND action_type = 'retrigger_payout'
--     AND  status IN ('pending','success')
--     AND  date(created_at) = date('now');
--
-- A ticket's full story (agent + human + merchant, in order):
--   SELECT created_at, actor, actor_id, event_type, detail
--   FROM   ticket_events WHERE ticket_id = 'TKT-77201' ORDER BY created_at;
--
-- Money decisions + outcome on that ticket:
--   SELECT a.ts, a.actor, a.action_type, a.amount, a.guardrail_decision,
--          a.reason_code, e.status, e.result_ref
--   FROM   audit_log a LEFT JOIN executions e ON e.audit_id = a.id
--   WHERE  a.ticket_id = 'TKT-77201' ORDER BY a.ts;
--
-- Open human handoffs (agent-desk queue):
--   SELECT id, merchant_id, reason_code, decision_needed, created_at
--   FROM   handoffs WHERE status = 'open' ORDER BY created_at;
-- ------------------------------------------------------------

-- NOTES
--  * audit_log = immutable decisions; executions = mutable execution state;
--    ticket_events = broad operational history. Three tables, three purposes.
--  * Guardrail decision is deterministic code, never an LLM.
--  * actor = how you prove "AI did this step" vs "human/merchant did this step".
--  * Stage demo: `UPDATE audit_log SET amount = 1;` -> ABORT append-only.
