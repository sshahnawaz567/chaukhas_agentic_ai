# Chaukas: deploy guide (Render for the API, Vercel for Member 3's UI)

> **Owner:** Member 2 (backend deploy, smoke test) · Member 3 (UI deploy on Vercel).
> Sirf **synthetic data** hai (koi asli merchant nahi). Ye prototype demo hai, production nahi.

## 1. Kaun kahan chalega

| Kya | Kahan | Kyun |
|---|---|---|
| **Backend** (FastAPI, SQLite, guardrail, agents) | **Render** (web service) | Ek lagatar chalne wala process chahiye: SQLite file, PII token vault aur step counters **memory mein** hain, aur LLM turns 2-5 s lete hain |
| **UI** (Member 3 ka React/Vite app) | **Vercel** (ya Lovable ka apna hosting) | Static site hai, Vercel iske liye bilkul theek |

**Backend ko Vercel par mat chalao.** Vercel serverless hai: har request alag instance par ja sakti hai, to SQLite file, PII vault aur counters kho jaate hain, aur request ki time limit hoti hai. Render par ek hi process chalta hai (`--workers 1`, `render.yaml` mein likha hai; ek se zyada worker PII `detokenise` tod dega).

## 2. Backend: Render par (10 minute)

1. Is branch/repo ko GitHub par `main` mein merge rakho. Render GitHub se code uthata hai.
2. Render dashboard > **New** > **Blueprint** > repo chuno > `render.yaml` apne aap padh lega.
3. Dashboard mein ye **secrets** daalo (kabhi git mein nahi):
   - `SARVAM_API_KEY`
   - `GEMINI_API_KEY` (fallback ke liye, optional)
4. **Apply** dabao. Build: `pip install -r requirements-deploy.txt`, phir eval replay chalta hai (~10 s) jo scorecard (`eval/latest.json`) banata hai. Start: `uvicorn ... --workers 1`.
5. Deploy ke baad URL milega: `https://chaukas-xxxx.onrender.com`. Pehle `GET /health` kholo, `{"status":"ok"}` aana chahiye.
6. **Smoke test chalao** (apne laptop se):
   ```
   python -m eval.smoke_deployed https://chaukas-xxxx.onrender.com
   ```
   Sab `PASS` hone chahiye (14 checks). `--full` ek insurance conversation bhi chalata hai, par wo deployed data badalta hai (M017 ka lead), to uske baad service **Restart** karo (DB dobara seed hoti hai).

### Env vars (render.yaml mein)

| Variable | Value | Matlab |
|---|---|---|
| `PYTHON_VERSION` | `3.11.9` | wahi version jisme tests chale |
| `CHAUKAS_PUBLIC_DEMO` | `1` | public URL par login nahi hai, isliye **erasure endpoint band** (403). Warna koi bhi demo merchants mita sakta hai |
| `CHAUKAS_REPLAY_MODE` | `off` | live Sarvam/Gemini. Agar LLM fail ho to keyword + templates par girta hai (demo kabhi chup nahi hota) |
| `CHAUKAS_CORS_ORIGINS` | UI ka exact https URL | **sirf agar** UI aur API alag origin par hain aur UI seedha API URL call karti hai (neeche option B). Kabhi `*` nahi |
| `SARVAM_API_KEY`, `GEMINI_API_KEY` | secret | LLM keys |
| `CHAUKAS_LOG_LEVEL` | `INFO` | logs |

## 3. UI: Vercel par (Member 3)

UI repo mein nahi hai (Member 3 ke paas hai), to Vercel wala hissa unka. Do tareeke:

**Option A (recommended): proxy, UI ka code nahi badalna.** UI ke repo mein `vercel.json`:
```json
{ "rewrites": [ { "source": "/api/:path*", "destination": "https://chaukas-xxxx.onrender.com/api/:path*" } ] }
```
Browser ko lagta hai API usi site par hai, to **CORS ki zaroorat nahi** aur `CHAUKAS_CORS_ORIGINS` khaali rahega. (Ye tab chalta hai jab UI relative `/api/...` call karti hai, jaise local Vite proxy mein.)

**Option B: seedha API URL.** UI mein env var (jaise `VITE_API_BASE=https://chaukas-xxxx.onrender.com`) se base URL do, aur Render par `CHAUKAS_CORS_ORIGINS=https://<tumhara-ui>.vercel.app` set karo (exact URL, comma se alag, trailing slash nahi).

Dono mein: Vercel par `VITE_USE_MOCK` **band** (false) rakhna, warna UI mock JSON dikhayegi.

## 4. Free plan ki sachchai (demo se pehle padho)

- **Neend:** free Render instance ~15 minute idle rehne par so jaata hai. Pehli request ko jagne mein ~50-60 s lagte hain. **Demo se 5 minute pehle `/health` kholo** (ya `python -m eval.smoke_deployed <url>`), aur recording se pehle bhi.
- **Disk mitt jaati hai:** restart/redeploy/neend ke baad file system fresh hota hai, aur DB **dobara seed** hoti hai. Yaani consents, leads, tickets sab reset (demo ke liye achha: har baar saaf shuruaat). Par demo ke **beech** mein neend aayi to state ud jaayegi: demo chalate waqt tab kholke rakho.
- Zyada bharose ke liye paid instance (no sleep) lo, ya ek pinger se `/health` ko har 10 minute hit karao.
- LLM live hai, to har turn 2-5 s leta hai (Sarvam ki speed badalti rehti hai, 2.2 s se 4.6 s dekhi gayi). Latency ka asli number scorecard mein hai.

## 5. Security aur data

- Public URL par **koi login nahi**. Isliye: erasure band (`CHAUKAS_PUBLIC_DEMO=1`), CORS band jab tak origin na do, aur sirf synthetic data.
- Secrets sirf Render dashboard mein. `.env` git mein nahi jaata (`.gitignore`).
- Mock OTP (`123456`, `config/mock.yaml`) sirf demo ke liye hai. Real merchant ya real paisa kabhi nahi.
- `GET /api/audit`, `/api/traces/...` masked data dikhate hain (raw PII nahi), par phir bhi ye demo ke liye hain.

## 6. Demo-day checklist

- [ ] Render service "Live" hai, `/health` ok
- [ ] `python -m eval.smoke_deployed <url>` = sab PASS
- [ ] UI (Vercel) `VITE_USE_MOCK` band, API se jud rahi hai (browser mein ek chat turn chalao)
- [ ] M017 (QR) aur M004 (insurance chip) ek baar chalake dekh lo, phir **service restart** (state saaf)
- [ ] 5 minute pehle instance jagao
- [ ] Backup: laptop par `uvicorn chaukas.main:app` (local) tayyar rakho

## 7. Rollback / dobara deploy

- Galat deploy hua: Render > Events > purana deploy > **Rollback**.
- Code badla: `main` mein merge karo, `autoDeploy: true` hai to apne aap deploy hota hai.
- Local par bilkul waisa chalane ke liye: `pip install -r requirements-deploy.txt`, `python -m eval.run_eval --llm replay`, `python -m uvicorn chaukas.main:app --port 8000 --workers 1`.
