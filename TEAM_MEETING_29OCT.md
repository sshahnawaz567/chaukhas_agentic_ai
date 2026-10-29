# Team Meeting — 29 Oct 2026 (evening) · ~90 min

> Goal: is meeting ke end tak **sab kuch freeze** ho, har member ko pata ho kal aur 31 ko kya karna hai.
> Meeting se pehle (15 min): sab `CHAUKAS_EXPLAINED.md` aur apni `MEMBER_X.md` file skim kar lo.

---

## 1. Update — ab tak kya ho gaya (10 min)

| Done | File |
|------|------|
| DB schema v3 (11 tables, append-only audit, DB-level "no execution without ALLOW") — tested | `data/schema.sql` |
| 20 test merchants, har ek ek scenario; lender rule verified on all 20 | `data/merchant_fixtures.json` |
| Poora design Hinglish mein + 14 judge Q&A | `CHAUKAS_EXPLAINED.md` |
| 6 shared contracts (models, guardrail, tools, privacy, API, config) — **PROPOSED** | `CONTRACTS.md` |
| 5-scene demo, video script, deck outline, timeline, fallbacks | `DEMO_SCRIPT.md` |
| Member docs updated to latest design + har member ke exact folders | `MEMBER_1/2/3_*.md` |
| Code skeleton (folders + empty files with owner docstrings), agents in `chaukas/agents/` | `CONTRACTS.md` §C6 |
| RBI FREE-AI / Digital Lending / DPDP Act 2023 → controls → files map | `COMPLIANCE.md` |

**Badi changes jo sabko pata honi chahiye:**
- Guardrail ab **10 checks** (pehle 6) — ledger match, daily limit (split attack), offer gating, BLOCK final.
- **Privacy Member 3 → Member 2** shift (proposal).
- Loan: **"Lender decides how much, Chaukas decides whether & when"** — simulated lender, placeholder thresholds.
- Over-limit demo mein **human approve** karta hai (agent-desk) → merchant OTP ab P1.
- Intent list final: `settlement_delay, loan_inquiry, device_issue, refund_request, confirm, deny, unknown`.

---

## 2. Decide karna hai (40 min) — har ek pe haan/na, owner ke saath

| # | Decision | Recommendation | Final |
|---|----------|----------------|-------|
| D1 | **UI kaun banayega?** | Member 3 (demo/video bhi wahi kar rahi hai, screens uske hisaab se) | |
| D2 | UI framework | Plain HTML/JS (ya React agar koi fast hai), FastAPI se serve. Streamlit nahi | |
| D3 | Privacy owner | Member 2 (PII-leak test bhi wahi likhega) | |
| D4 | Demo ke 5 scenes (`DEMO_SCRIPT.md` §2) | Approve as-is | |
| D5 | Guardrail 10 checks + order (`CONTRACTS.md` §C2) | Approve | |
| D6 | ₹25,000 exactly | ALLOW (`<=`) | |
| D7 | Over-limit confirmation | Human approve (demo) · merchant OTP = P1 | |
| D8 | Human approval daily limit bypass kar sakta hai? | Haan (checks 8–10), BLOCK kabhi nahi (1–7) | |
| D9 | Intent confidence threshold | 0.7 | |
| D10 | History window in state | Last 6 turns | |
| D11 | Build-day rules | 3 PM voice cut-off · **4 PM feature freeze** · har 2 ghante integration | |
| D12 | Q&A ownership | Problem/business → M3 · architecture/LLM → M1 · safety/eval → M2 | |
| D14 | Hamara "offer cooling-off" (decline ke 7 din baad tak dobara offer nahi) RBI ke loan **cooling-off period** (loan lene ke baad bina penalty exit) se confuse hoga | Rename: `OFFER_RECENTLY_DECLINED` / `offer_redecline_gap_days` | |
| D15 | Compliance scope (`COMPLIANCE.md`) — P0 rows OK? KFS card + "Talk to a human" + kill switch P0, consent toggle + fairness test P1 | Approve | |
| D13 | Sab ok? → `CONTRACTS.md` status **FROZEN v1** | — | |

---

## 3. Abhi bhi pending / unknown (10 min) — owner assign karo

| # | Item | Kyun important | Owner | By |
|---|------|----------------|-------|----|
| P1 | **Organisers: pre-built code allowed?** | Allowed → aaj-kal skeleton likh lo, 31 ko sirf integrate. Ye sabse bada farak hai | | Kal subah |
| P2 | Organisers: exact end time, submission format, video length, live demo/Q&A hai?, venue internet | Timeline + fallback plan isi pe | | Kal subah |
| P3 | **Sarvam-30B + Gemini API keys test** (20 Hinglish messages: intent, JSON, latency) | Venue pe pata chala ki model kamzor hai = disaster | M1 | Aaj raat |
| P4 | Sarvam Saaras/Bulbul (voice) key test | Voice P1, lekin key pehle check | M1 | Kal |
| P5 | Git repo + `requirements.txt` + same Python version sab laptops pe, dependencies pre-installed | Venue wifi pe `pip install` mat karna | M1 | Kal |
| P6 | Prompts draft (intent, reply, handoff) + test | Code nahi hai, aaj ho sakta hai | M1 | Kal |
| P7 | `golden_set.json` + `redteam_set.json` (data hai, code nahi) | Eval build day pe sirf runner likhna pade | M2 | Kal |
| P8 | `policy.yaml` draft + 10-check unit test case list | | M2 | Kal |
| P9 | Deck skeleton (Claude Code prompt ready hai) + video title/closing cards + OBS test | | M3 | Kal |
| P10 | Sample `TurnResponse` JSON per scene (UI ke liye) | UI backend ka wait na kare | M1 → M3 | Kal |
| P11 | Stage 1 deck reuse kahan tak? | | M3 | Kal |
| P12 | Laptops: charger, extension board, hotspot backup, HDMI adapter | Silly cheez, lekin demo maar sakti hai | Sab | 30 Oct |

---

## 4. Teach-back (15 min) — har member 2 sawaal bina doc dekhe

`CHAUKAS_EXPLAINED.md` §14 se. Jo atke, wo section kal padh ke aaye.
- M1 se: Q3 (injection), Q13 (audit badal de to?)
- M2 se: Q1 (Soundbox se kya naya), Q10 (human kahan hai)
- M3 se: Q2 (LLM kam kyun), Q8 (loan formula)

---

## 5. Meeting ke end mein — checklist

- [ ] D1–D13 sab "Final" column mein filled
- [ ] `CONTRACTS.md` → FROZEN v1 (ya changes list ke saath "freeze kal 12 baje tak")
- [ ] P1–P12 har ek ka owner + deadline
- [ ] Kal ka sync time fix (e.g. 30 Oct shaam 30 min — progress + organiser jawab)
- [ ] 31 Oct: kaun kab nikalega, 9 AM venue
