# Member 3 — Interface + Demo + Video + Deck

> **Project:** Chaukas (चौकस) · **Team:** Enver AI · **Track 3 — Autonomous AI Teammates**
> **Your role:** Everything the judges see — the UI, the live demo, the video, the deck, and the submission.
> **Read first:** `DEMO_SCRIPT.md` (**your main playbook**) → `CHAUKAS_EXPLAINED.md` (whole design, Hinglish) → `CONTRACTS.md` §C5 (API you call).
> **Updated:** 29 Oct 2026. Supersedes the earlier version of this file. **Privacy moved to Member 2.** File name kept the same so links don't break.
> ⚠️ **UI ownership is a proposal — confirm in today's meeting.** If the UI moves to someone else, sections 2–3 move with it.

---

## 1. What you own

**Your folders** (full tree with everyone's files: `CONTRACTS.md` §C6):

```
ui/                            ★ all 6 demo panels (DEMO_SCRIPT §4) — framework decided in team meeting
README.md                      repo root: what it is, 3-command run, what's mocked
deck/                          Chaukas_Finals.pptx (+ screenshots/ for S1–S10)
video/                         clips, voiceover, final export (gitignore large files)
```

You don't own any `chaukas/` Python files — you call the API (`CONTRACTS.md` §C5). The backend files for your panels: `chaukas/api/chat.py`, `desk.py` (Member 1), `ops.py` (Member 2).

| Area | Deliverable |
|------|-------------|
| **UI** | 6 panels from `DEMO_SCRIPT.md` §4: merchant chat, trace panel, agent-desk (handoff queue + brief + approve + ticket timeline), audit panel, red-team panel, eval scorecard |
| **Demo** | Live demo flow, rehearsal, fallback switch (`DEMO_SCRIPT.md` §3, §9) |
| **Video** | 3-min video, voiceover, recording (`DEMO_SCRIPT.md` §5) |
| **Deck** | ~14 slides, real screenshots + real numbers (`DEMO_SCRIPT.md` §6) |
| **Submission** | `README.md`, final checklist (`DEMO_SCRIPT.md` §10) |
| Voice (P1) | Mic button + audio playback in chat UI; backend endpoint is Member 1's |

**Compliance surfaces that are yours** (`COMPLIANCE.md`):
- "AI assistant" badge on every Chaukas message + disclosure as the first bubble (R1).
- "Talk to a human" button, always visible → sends `human_request` (R2, D8).
- **KFS card** on the loan offer: lender name, APR, fee, tenure, total repayable, grievance contact — shown **before** the Haan/Nahi buttons (L1, L2, L5).
- Consent toggle in chat settings (P1, D2, D3).
- Deck slide 9 (Safety & compliance) — use only the "safe to say" lines in `COMPLIANCE.md` §5. Never "RBI-compliant" or "certified".

---

## 2. UI — what matters

- **Layout:** left = merchant chat, right = trace panel. This is the main demo screen and the clearest in a video.
- **Guardrail verdicts must be impossible to miss:** 🟢 ALLOW / 🟡 NEEDS_CONFIRMATION / 🔴 BLOCK, with the reason in large text ("amount 32500 > auto_limit 25000"). This is the wow moment.
- **Agent-desk** is a separate view: open handoffs → brief card (asked / verified / done / refused / confidence / **decision needed**) → "Approve & execute" → ticket timeline showing `agent` vs `human`.
- Merchant dropdown shows the `scenario` label (from `/api/merchants`) so demo setup is one click.
- Hindi (Devanagari) must render properly. Min font 16 px — it'll be recorded at 1080p.
- **Framework:** decide in today's meeting. Recommendation: plain HTML/JS (or React if you're fast with it), served by FastAPI. Avoid Streamlit (two views + live updates get awkward).

---

## 3. Build against mock JSON first

Don't wait for the backend. From `CONTRACTS.md` §C5, write one sample `TurnResponse` JSON per scene (Member 1 will confirm) and build every panel against those files. Swap to real API calls when Member 1's skeleton is up (~11:00).

---

## 4. Priorities

| Priority | Item | Scene |
|----------|------|:---:|
| **P0** | Chat + trace panel with colour-coded verdicts + consent buttons | 1, 2 |
| **P0** | Agent-desk: queue, brief, approve, ticket timeline | 3 |
| **P0** | Audit panel, red-team panel, scorecard | 4, 5 |
| **P0** | Video recorded + deck with real screenshots/numbers + README | — |
| **P1** | Voice mic + playback (only if Member 1's endpoint works by 3 PM) | 1 |
| **P1** | Naive-agent side-by-side view | 4 |

---

## 5. Before build day (29–30 Oct)

- [ ] Read `DEMO_SCRIPT.md` fully and `CHAUKAS_EXPLAINED.md` §14 (judge Q&A).
- [ ] **Deck skeleton** — all 14 slides, text + diagrams, grey `[S#]` boxes for screenshots, `[N]` for numbers. (A ready-made Claude Code prompt for this exists — ask the team.)
- [ ] **Video assets** — title card, closing card, problem slide; rehearse the voiceover with a timer.
- [ ] **OBS** installed + one test recording at 1080p.
- [ ] UI mock-ups / sample JSON per scene; if pre-built code is allowed, build the static UI now.
- [ ] `README.md` draft.
- [ ] Send the organiser questions (`DEMO_SCRIPT.md` §10) and share the answers.

---

## 6. Build day (31 Oct)

Full timeline in `DEMO_SCRIPT.md` §8. Key checkpoints:

| Time | Must be true |
|------|--------------|
| 11:00 | UI calling Member 1's skeleton API |
| 1:30 | Scenes 1 + 2 work in the UI → capture S1–S3 |
| 3:00 | Scenes 3 + 4 in UI → capture S4–S6; voice go/no-go |
| 4:00 | Full rehearsal done, **feature freeze** |
| 4:30 | Real eval numbers from Member 2 → deck + video |
| 5:45 | Video + deck + README ready → **submit** |

---

## 7. Dependencies

- **Member 1 → you:** API exactly as `TurnResponse` (C5); sample JSON per scene early.
- **Member 2 → you:** audit rows, red-team results, scorecard JSON; final numbers by 4:30.
- **You → both:** bug reports from rehearsal (3:00–4:00), screenshots for the deck, the 4 PM freeze call.

---

## 8. Definition of done

- [ ] All 5 demo scenes run from the UI on a fresh-seeded DB.
- [ ] Video ≤ limit, 1080p, clear audio, link checked in incognito.
- [ ] Deck: real screenshots, real numbers, "Real vs Mocked" slide present.
- [ ] README: a fresh clone runs in ≤ 3 commands.
- [ ] Same claims and same numbers across prototype, video, deck.

---

## 9. Judge questions you must own

- Paytm already has an AI Soundbox — what's new? → Soundbox talks; Chaukas does the work after the talk, with verified execution.
- Business value? → fewer manual settlement fixes, resolution in one conversation, loan offers at the moment of highest trust (with consent).
- How does it work alongside humans? → agent-desk: decision brief, one-click approve that still goes through the guardrail, `actor` trail.
- What's real and what's mocked? → agents, guardrail, audit, eval, UI are real; Paytm payout/CRM/lending APIs and the lender model are mocked.
- Full list: `CHAUKAS_EXPLAINED.md` §14.
