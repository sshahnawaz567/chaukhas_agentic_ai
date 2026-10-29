"""Turn state machine: intent -> context -> plan -> (guardrail -> action | pending | handoff) -> reply.
Invariant: no path reaches action.run() without an ALLOW from guardrail.check().

Owner: Member 1 · Contract: CONTRACTS C1.4
"""
