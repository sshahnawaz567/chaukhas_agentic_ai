"""Shared pytest fixtures: fresh in-memory DB seeded from fixtures.

Owner: Member 2 · Contract: —

Each test gets its own freshly seeded SQLite file (tmp_path), so tests never share state.
"""
import pytest

from chaukas.core.models import (
    Channel, ConversationState, LenderDecision, MerchantContext, Mode, PlannedStep,
)
from chaukas.db import connect
from chaukas.policy import engine
from data.seed import seed

OTP = "123456"


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    seed(path)
    conn = connect(path)
    yield conn
    conn.close()


@pytest.fixture
def policy():
    return engine.load_policy()


@pytest.fixture(scope="session", autouse=True)
def agent_logs_in_tmp(tmp_path_factory):
    """Member 1's agents write logs/session_<id>/ for every session. Tests open hundreds of sessions, so point
    the log folder at a temp dir for the whole run (session scope also covers module-scoped fixtures)."""
    mp = pytest.MonkeyPatch()
    mp.setenv("CHAUKAS_AGENT_LOG_DIR", str(tmp_path_factory.mktemp("agent_logs")))
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def mock_otp(monkeypatch):
    """config/mock.yaml belongs to Member 1; tests pin the OTP so they do not depend on it."""
    monkeypatch.setattr(engine, "load_mock_otp", lambda: OTP)
    return OTP


@pytest.fixture
def make_state():
    def build(merchant_id: str, session_id: str = "S1", eligible: tuple[bool, int] | None = None):
        """eligible=(True, 50000) puts a simulated-lender answer in state.merchant.eligibility."""
        merchant = None
        if eligible is not None:
            merchant = MerchantContext(
                merchant_id=merchant_id, name_masked="Sh****", account_ref="tok_account_no_00000000",
                preferred_lang="hi-IN", kyc_status="verified", device=None, gmv_30d=0,
                bank_details_updated_at=None, settlements=[], open_tickets=[], has_open_handoff=False,
                declined_offer_recently=False,
                eligibility=LenderDecision(eligible=eligible[0], max_amount=eligible[1], reason_codes=[]))
        return ConversationState(
            session_id=session_id, turn_no=1, trace_id=f"trace-{session_id}", merchant_id=merchant_id,
            channel=Channel.CHAT, mode=Mode.AUTONOMOUS, message_masked="test", merchant=merchant)
    return build


@pytest.fixture
def make_step():
    def build(action: str, params: dict, step_no: int = 1, amount: int | None = None, reversible: bool = True):
        if amount is None:
            amount = params.get("amount") if isinstance(params.get("amount"), int) else None
        return PlannedStep(step_no=step_no, action_type=action, params=params, amount=amount,
                           reversible=reversible, rationale="test")
    return build
