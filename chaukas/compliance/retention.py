"""Retention + erasure (P2): purge/anonymise `turns` after the retention window;
on an erasure request anonymise the merchant's PII everywhere EXCEPT records the
law requires us to keep (audit_log stays — it never holds raw PII anyway).

Owner: Member 2 · COMPLIANCE.md D6, D7
"""
