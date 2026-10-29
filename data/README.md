Intent list (final — CONTRACTS.md §C1.1). Agent sabse pehle intent classify karta hai:

settlement_delay — paisa nahi aaya (failed ya pending settlement)
loan_inquiry     — loan chahiye
device_issue     — soundbox / POS / QR mein problem → ticket
refund_request   — customer ko paisa wapas dena hai → hamesha handoff (refund tool by design nahi hai)
confirm          — pending step ka "haan" (e.g. "haan bhejo")
deny             — pending step ka "nahi"
human_request    — "insaan se baat karao" / shikayat → hamesha handoff (RBI FREE-AI, DPDP)
unknown          — samajh nahi aaya / low confidence → handoff

merchant_fixtures.json ka structure aur har merchant ka scenario: file ke "_meta" section mein,
aur CHAUKAS_EXPLAINED.md §8 mein.

⚠ golden_set.json aur redteam_set.json STALE hain (purane design se): purane intents (loan_offer),
lang "hinglish" (ab BCP-47 jaise hi-IN), aur action names jo ActionType se match nahi karte
(fetch_merchant_context, diagnose_settlement_failure, ...). Kuch expectations v3 fixtures se
galat hain (jaise G01: M001 ka ab failed settlement SET-99213 hai). Rewrite = Member 2 ka task P7,
CONTRACTS.md C1 (intents, ActionType, ReasonCode) aur C2 (red-team expectations) ke hisaab se.
