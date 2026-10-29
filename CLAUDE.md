# Chaukas — instructions for Claude Code

Chaukas (चौकस) is a hackathon prototype for Paytm Build for India, Track 3 (Autonomous AI Teammates). It is an AI teammate for Paytm merchants. It understands a merchant's problem in their language, plans a fix, runs every money action through a **deterministic guardrail** before executing it through **mock** APIs, and hands a human a decision brief when it should. Finals build day: **31 Oct 2026, ~9 AM to evening**. A team of 3 builds it.

## Who you are working for

There are 3 team members, and each one owns a part of the codebase. **At the start of a session, if you don't already know which member you are helping, ask.** Then read that member's file **fully**, plus the files it tells you to read:

| Member | Owns | Start here |
|--------|------|-----------|
| Member 1 | Agent core + API: models, orchestrator, LLM agents, mocks, FastAPI | `MEMBER_1_AGENT_CORE.md` |
| Member 2 | Guardrail + data + privacy + compliance + eval | `MEMBER_2_GUARDRAIL_EVAL.md` |
| Member 3 | UI + demo + video + deck + submission | `MEMBER_3_INTERFACE_PRIVACY_DEMO.md` |

## Document map (what each file is for)

| File | Read it when |
|------|-------------|
| `CONTRACTS.md` | **Before writing any code.** It holds the exact shared models (C1), the guardrail contract (C2), tool signatures (C3), privacy functions (C4), API (C5), and the repo layout plus file owners (C6). It is the source of truth for names, types and file locations. |
| `data/schema.sql` | Before touching the DB or anything that reads or writes it. The table and column names here are final. |
| `data/merchant_fixtures.json` | The seed data. There are 20 merchants, and each one has a `scenario` label. The `_meta` section holds conventions, the simulated-lender rule, `cause_to_plan`, and offer gating. |
| `COMPLIANCE.md` | Before building anything user-facing, consent-related, loan-related or PII-related. It maps RBI FREE-AI, RBI Digital Lending and the DPDP Act 2023 to concrete controls. |
| `DEMO_SCRIPT.md` | It defines what must work on stage: 5 scenes with exact inputs and expected outputs. **Priorities come from here.** |
| `CHAUKAS_EXPLAINED.md` | A full design explanation in Hinglish, with the *why* behind every decision. §14 holds the judge Q&A. |
| `CHAUKAS_SYSTEM_DESIGN.md` | The HLD/LLD background. Where it conflicts with `CONTRACTS.md`, **CONTRACTS wins** (B1, B2 and B10 are marked superseded). |
| `CHAUKAS_PROBLEM_STATEMENT.md` | The problem, scope, tech stack, and the acceptance metrics. |
| `TEAM_MEETING_29OCT.md` | Open team decisions (D1–D15) and pending tasks (P1–P12). |

## Non-negotiable rules

1. **The guardrail is deterministic Python. Never use an LLM inside it.** No code path may execute an action without an ALLOW `Decision`. The DB also enforces this through the `executions_require_allow` trigger, so never remove or bypass that trigger.
2. **Money amounts come from the ledger, never from the merchant's message.** Amounts are `int` rupees, never `float`.
3. **BLOCK is final.** No confirmation, whether from the merchant or a human, turns a BLOCK into an ALLOW.
4. **Never cache money state.** That covers settlements, balances, payouts and guardrail decisions.
5. **No raw PII** may reach logs, traces, `audit_log`, `turns`, `handoffs` or LLM prompts. Route it through `chaukas/privacy/` (`mask`, `mask_text`, `tokenise`, `scrub`). Only `chaukas/agents/action.py` may call `detokenise()`.
6. **`audit_log` and `consents` are append-only.** Never write UPDATE or DELETE against them.
7. **Config lives in `config/*.yaml` and prompts live in `prompts/*.v1.txt`.** Never hardcode limits, thresholds or prompt text.
8. **No LangChain or LangGraph.** Use plain Python with FastAPI and Pydantic v2. Every external service (payments, tickets, lending) is a deterministic **mock**.
9. **Shared models live only in `chaukas/core/models.py`.** Never redefine `PlannedStep`, `Decision` or the others elsewhere.
10. In pitch-facing text, never say "RBI-compliant" or "certified". Say "aligned with".

## Working rules

- **Stay inside your member's files** (the owners are listed in CONTRACTS §C6). If a change needs another member's file or a **shared file**, stop and tell the user. The shared files are `chaukas/core/models.py`, `data/schema.sql`, `CONTRACTS.md`, `config/policy.yaml` and `requirements.txt`. These need a PR approved by another member.
- **The contracts are additive-only once frozen.** You may add new optional fields or enum values. Renaming or removing anything needs team agreement.
- **Every skeleton file already exists with a docstring** that states its purpose, owner and contract. Read the docstring before you write the file.
- **Build in priority order:** P0 items first (each member file has a priority table), then P1. Build P2 only if idle.
- **Git:** short task branches named `m1/…`, `m2/…` or `m3/…`, a PR into `main`, and a merge every 1–2 hours. Never force-push `main`. Never commit `.env` or `data/*.db`.
- After 4 PM on build day, make **bug fixes only**, with no new features.

## Commands

- Run everything from the repo root, and use absolute imports (`from chaukas.core.models import PlannedStep`).
- Install: `pip install -r requirements.txt` (Python 3.11)
- Seed the DB: `python -m data.seed`, which writes `data/chaukas.db`
- Run the API: `uvicorn chaukas.main:app --reload`
- Run the tests: `pytest`
- Run the eval: `python -m eval.run_eval`, then `python -m eval.redteam`
- Secrets go in `.env`. Copy it from `.env.example`.

## Known stale items

- `data/golden_set.json` and `data/redteam_set.json` follow the **old** design (old intents and action names). Member 2 rewrites them under task P7. Do not build eval logic around their current shape.
