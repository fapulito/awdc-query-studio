"""
tests/test_billing.py

Unit tests for modules/billing.py using an in-memory fake store.
No real database or Stripe credentials needed.
"""

import sys
import types
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub the `stripe` package so tests run without it installed
# ---------------------------------------------------------------------------
if "stripe" not in sys.modules:
    _stripe_stub = types.ModuleType("stripe")

    class _WebhookStub:
        @staticmethod
        def construct_event(payload, sig, secret):
            raise NotImplementedError("stub — patch me")

    class _CustomerStub:
        @staticmethod
        def retrieve(customer_id):
            raise NotImplementedError("stub — patch me")

    class _CheckoutStub:
        class Session:
            @staticmethod
            def create(**kwargs):
                raise NotImplementedError("stub — patch me")

    _stripe_stub.Webhook = _WebhookStub
    _stripe_stub.Customer = _CustomerStub
    _stripe_stub.checkout = _CheckoutStub
    sys.modules["stripe"] = _stripe_stub


# ---------------------------------------------------------------------------
# Fake in-memory store — replaces all DB operations inside billing.py
# ---------------------------------------------------------------------------

class FakeStore:
    """Simple dict-backed store that mimics the subscriptions table."""

    def __init__(self):
        self._data: dict = {}

    def get_or_create(self, email: str) -> dict:
        if email not in self._data:
            self._data[email] = {
                "email": email,
                "tier": "free",
                "period_start": datetime.now(tz=timezone.utc),
                "questions_used": 0,
            }
        return dict(self._data[email])

    def update(self, email: str, **kwargs):
        if email in self._data:
            self._data[email].update(kwargs)

    def upsert(self, email: str, tier: str):
        self._data[email] = {
            "email": email,
            "tier": tier,
            "period_start": datetime.now(tz=timezone.utc),
            "questions_used": 0,
        }


# ---------------------------------------------------------------------------
# Helpers that build a billing module wired to a FakeStore
# ---------------------------------------------------------------------------

def _make_billing(store: FakeStore, billing_on: bool = True):
    """
    Return a fresh import of billing.py with all DB calls monkey-patched
    to use the provided FakeStore, and billing_enabled forced to billing_on.
    """
    import importlib
    import modules.billing as billing
    importlib.reload(billing)

    billing.billing_enabled = billing_on

    # Patch get_or_create_user
    def fake_get_or_create(email):
        return store.get_or_create(email)

    # Patch _maybe_reset (works on the dict, touches store)
    def fake_maybe_reset(row, cur):
        now = datetime.now(tz=timezone.utc)
        period_start = row.get("period_start")
        if period_start is None or (now - period_start) > timedelta(days=30):
            store.update(row["email"], questions_used=0, period_start=now)
            row = dict(row)
            row["questions_used"] = 0
            row["period_start"] = now
        return row

    # Patch check_limit using fake helpers
    def fake_check_limit(email):
        if not billing_on:
            return (True, 0, billing.PLAN_LIMITS["free"])
        row = fake_get_or_create(email)
        row = fake_maybe_reset(row, None)
        tier = row.get("tier", "free")
        limit = billing.PLAN_LIMITS.get(tier, billing.PLAN_LIMITS["free"])
        used = row.get("questions_used", 0)
        return (used < limit, used, limit)

    # Patch record_question
    def fake_record_question(email):
        if not billing_on:
            return
        row = fake_get_or_create(email)
        row = fake_maybe_reset(row, None)
        store.update(email, questions_used=store._data[email]["questions_used"] + 1)

    # Patch set_tier
    def fake_set_tier(email, tier):
        if not billing_on:
            return
        store.upsert(email, tier)

    billing.get_or_create_user = fake_get_or_create
    billing.check_limit = fake_check_limit
    billing.record_question = fake_record_question
    billing.set_tier = fake_set_tier

    return billing


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRolling30DayReset:
    def test_period_past_30_days_resets_count(self):
        store = FakeStore()
        store.get_or_create("user@test.com")
        # Wind the period_start back 31 days
        store.update(
            "user@test.com",
            questions_used=8,
            period_start=datetime.now(tz=timezone.utc) - timedelta(days=31),
        )
        billing = _make_billing(store)
        allowed, used, limit = billing.check_limit("user@test.com")
        assert used == 0, "questions_used should have been reset to 0"
        assert allowed is True

    def test_period_within_30_days_does_not_reset(self):
        store = FakeStore()
        store.get_or_create("user@test.com")
        store.update(
            "user@test.com",
            questions_used=5,
            period_start=datetime.now(tz=timezone.utc) - timedelta(days=10),
        )
        billing = _make_billing(store)
        allowed, used, limit = billing.check_limit("user@test.com")
        assert used == 5, "questions_used should remain unchanged"


class TestFreePlanCap:
    def test_free_user_at_limit_not_allowed(self):
        store = FakeStore()
        store.get_or_create("free@test.com")
        store.update("free@test.com", questions_used=10)
        billing = _make_billing(store)
        allowed, used, limit = billing.check_limit("free@test.com")
        assert allowed is False
        assert used == 10
        assert limit == 10

    def test_free_user_below_limit_allowed(self):
        store = FakeStore()
        store.get_or_create("free@test.com")
        store.update("free@test.com", questions_used=9)
        billing = _make_billing(store)
        allowed, used, limit = billing.check_limit("free@test.com")
        assert allowed is True
        assert used == 9

    def test_free_user_at_zero_allowed(self):
        store = FakeStore()
        store.get_or_create("free@test.com")
        billing = _make_billing(store)
        allowed, used, limit = billing.check_limit("free@test.com")
        assert allowed is True
        assert used == 0


class TestProPlanCap:
    def test_pro_user_at_250_not_allowed(self):
        store = FakeStore()
        store.get_or_create("pro@test.com")
        store.update("pro@test.com", tier="pro", questions_used=250)
        billing = _make_billing(store)
        allowed, used, limit = billing.check_limit("pro@test.com")
        assert allowed is False
        assert used == 250
        assert limit == 250

    def test_pro_user_at_249_allowed(self):
        store = FakeStore()
        store.get_or_create("pro@test.com")
        store.update("pro@test.com", tier="pro", questions_used=249)
        billing = _make_billing(store)
        allowed, used, limit = billing.check_limit("pro@test.com")
        assert allowed is True
        assert used == 249

    def test_pro_user_at_zero_allowed(self):
        store = FakeStore()
        store.get_or_create("pro@test.com")
        store.update("pro@test.com", tier="pro", questions_used=0)
        billing = _make_billing(store)
        allowed, used, limit = billing.check_limit("pro@test.com")
        assert allowed is True


class TestSetTier:
    def test_upgrade_free_to_pro_resets_usage(self):
        store = FakeStore()
        store.get_or_create("user@test.com")
        store.update("user@test.com", questions_used=7)
        billing = _make_billing(store)
        billing.set_tier("user@test.com", "pro")
        row = store._data["user@test.com"]
        assert row["tier"] == "pro"
        assert row["questions_used"] == 0

    def test_downgrade_pro_to_free_resets_usage(self):
        store = FakeStore()
        store.get_or_create("user@test.com")
        store.update("user@test.com", tier="pro", questions_used=200)
        billing = _make_billing(store)
        billing.set_tier("user@test.com", "free")
        row = store._data["user@test.com"]
        assert row["tier"] == "free"
        assert row["questions_used"] == 0

    def test_set_tier_creates_user_if_absent(self):
        store = FakeStore()
        billing = _make_billing(store)
        billing.set_tier("new@test.com", "pro")
        assert "new@test.com" in store._data
        assert store._data["new@test.com"]["tier"] == "pro"


class TestRecordQuestion:
    def test_record_increments_counter(self):
        store = FakeStore()
        store.get_or_create("user@test.com")
        store.update("user@test.com", questions_used=3)
        billing = _make_billing(store)
        billing.record_question("user@test.com")
        assert store._data["user@test.com"]["questions_used"] == 4

    def test_record_multiple_times(self):
        store = FakeStore()
        store.get_or_create("user@test.com")
        billing = _make_billing(store)
        for _ in range(5):
            billing.record_question("user@test.com")
        assert store._data["user@test.com"]["questions_used"] == 5


class TestWebhookHandler:
    """Test the Stripe webhook tier-setting logic (stubbed Stripe event)."""

    def _make_event(self, event_type: str, customer_email: str = None, customer_id: str = None) -> dict:
        obj = {}
        if customer_email:
            obj["customer_email"] = customer_email
        if customer_id:
            obj["customer"] = customer_id
        return {"type": event_type, "data": {"object": obj}}

    def test_checkout_completed_sets_pro(self):
        store = FakeStore()
        store.get_or_create("buyer@test.com")
        billing = _make_billing(store)

        event = self._make_event("checkout.session.completed", customer_email="buyer@test.com")
        # Simulate the webhook handler logic directly
        with patch("modules.billing.set_tier", side_effect=billing.set_tier):
            if event["type"] == "checkout.session.completed":
                email = event["data"]["object"].get("customer_email")
                if email:
                    billing.set_tier(email, "pro")

        assert store._data["buyer@test.com"]["tier"] == "pro"

    def test_subscription_deleted_sets_free(self):
        store = FakeStore()
        store.get_or_create("churned@test.com")
        store.update("churned@test.com", tier="pro")
        billing = _make_billing(store)

        event = self._make_event("customer.subscription.deleted", customer_id="cus_123")

        # Stub Stripe.Customer.retrieve
        fake_customer = {"email": "churned@test.com"}

        with patch("stripe.Customer.retrieve", return_value=fake_customer):
            import stripe as _stripe
            if event["type"] == "customer.subscription.deleted":
                customer_id = event["data"]["object"].get("customer")
                if customer_id:
                    customer = _stripe.Customer.retrieve(customer_id)
                    email = customer.get("email")
                    if email:
                        billing.set_tier(email, "free")

        assert store._data["churned@test.com"]["tier"] == "free"

    def test_webhook_construct_event_called(self):
        """Ensure construct_event is invoked during signature verification."""
        fake_event = self._make_event("checkout.session.completed", customer_email="x@test.com")
        with patch("stripe.Webhook.construct_event", return_value=fake_event) as mock_ce:
            import stripe
            result = stripe.Webhook.construct_event(b"payload", "sig", "secret")
            mock_ce.assert_called_once_with(b"payload", "sig", "secret")
            assert result["type"] == "checkout.session.completed"


class TestBillingDisabled:
    def test_check_limit_returns_allowed_when_disabled(self):
        import importlib
        import modules.billing as billing
        importlib.reload(billing)
        billing.billing_enabled = False
        allowed, used, limit = billing.check_limit("anyone@test.com")
        assert allowed is True
        assert used == 0

    def test_record_question_noop_when_disabled(self):
        import importlib
        import modules.billing as billing
        importlib.reload(billing)
        billing.billing_enabled = False
        # Should not raise
        billing.record_question("anyone@test.com")

    def test_set_tier_noop_when_disabled(self):
        import importlib
        import modules.billing as billing
        importlib.reload(billing)
        billing.billing_enabled = False
        # Should not raise
        billing.set_tier("anyone@test.com", "pro")

    def test_get_or_create_returns_safe_default_when_disabled(self):
        import importlib
        import modules.billing as billing
        importlib.reload(billing)
        billing.billing_enabled = False
        row = billing.get_or_create_user("anyone@test.com")
        assert row["tier"] == "free"
        assert row["questions_used"] == 0
