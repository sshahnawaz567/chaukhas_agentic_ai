"""scrub(obj): deep copy with every PII value masked. Used by observability/* and
before writing turns/audit/handoffs.

Owner: Member 2 · Contract: CONTRACTS C4
"""
from typing import Any

from chaukas.privacy.pii import PII_FIELDS, mask, mask_text


def scrub(obj: Any) -> Any:
    """Return a deep copy of obj in which every PII value is masked. The input is never changed.

    - dict value under a PII key (account_no, phone, ...) -> mask(value, key)
    - any other string -> mask_text (PII hiding inside free text)
    - dict / list / tuple / set / Pydantic model -> scrubbed recursively
    """
    if isinstance(obj, str):
        return mask_text(obj)
    if hasattr(obj, "model_dump"):  # Pydantic model
        return scrub(obj.model_dump(mode="json"))
    if isinstance(obj, dict):
        return {key: _scrub_value(key, val) for key, val in obj.items()}
    if isinstance(obj, (list, set)):
        return [scrub(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(scrub(item) for item in obj)
    return obj  # int, float, bool, None: nothing to hide


def _scrub_value(key: Any, val: Any) -> Any:
    field = str(key).lower()
    if field in PII_FIELDS and val is not None and not isinstance(val, (dict, list, tuple, set)):
        return mask(str(val), field)
    return scrub(val)
