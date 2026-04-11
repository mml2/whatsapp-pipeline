import pytest
from pipeline.context_window import ContextWindow
from pipeline.models import WhatsAppMessage


def make_msg(message_id: str, timestamp: str, sender: str = "User") -> WhatsAppMessage:
    return WhatsAppMessage(
        message_id=message_id,
        timestamp=timestamp,
        sender=sender,
        group="Wayne Desi Gals",
        text="test message",
        media_type="text",
        quoted_message_id=None,
    )


# ---------------------------------------------------------------------------
# Basic add / retrieve
# ---------------------------------------------------------------------------

class TestBasicBehaviour:
    def test_empty_window_returns_empty_list(self):
        window = ContextWindow()
        assert window.get_recent("2024-01-15T10:00:00") == []

    def test_single_message_within_window_returned(self):
        window = ContextWindow()
        msg = make_msg("m1", "2024-01-15T09:30:00")
        window.add(msg)
        result = window.get_recent("2024-01-15T10:00:00")
        assert len(result) == 1
        assert result[0].message_id == "m1"

    def test_returns_whatsapp_message_instances(self):
        window = ContextWindow()
        window.add(make_msg("m1", "2024-01-15T09:30:00"))
        result = window.get_recent("2024-01-15T10:00:00")
        assert all(isinstance(m, WhatsAppMessage) for m in result)

    def test_len_reflects_buffer_size(self):
        window = ContextWindow()
        window.add(make_msg("m1", "2024-01-15T09:00:00"))
        window.add(make_msg("m2", "2024-01-15T09:30:00"))
        assert len(window) == 2


# ---------------------------------------------------------------------------
# 120-minute window boundary
# ---------------------------------------------------------------------------

class TestWindowBoundary:
    def test_message_exactly_at_cutoff_included(self):
        # cutoff = 10:00 - 120 min = 08:00; message at 08:00 should be included
        window = ContextWindow(minutes=120)
        window.add(make_msg("m1", "2024-01-15T08:00:00"))
        result = window.get_recent("2024-01-15T10:00:00")
        assert len(result) == 1

    def test_message_one_second_before_cutoff_excluded(self):
        # cutoff = 08:00; message at 07:59:59 is outside the window
        window = ContextWindow(minutes=120)
        window.add(make_msg("m1", "2024-01-15T07:59:59"))
        result = window.get_recent("2024-01-15T10:00:00")
        assert result == []

    def test_message_at_before_ts_excluded(self):
        # before_ts is the current message timestamp — must not appear in its own context
        window = ContextWindow(minutes=120)
        window.add(make_msg("m1", "2024-01-15T10:00:00"))
        result = window.get_recent("2024-01-15T10:00:00")
        assert result == []

    def test_message_after_before_ts_excluded(self):
        window = ContextWindow(minutes=120)
        window.add(make_msg("m1", "2024-01-15T10:01:00"))
        result = window.get_recent("2024-01-15T10:00:00")
        assert result == []

    def test_only_messages_within_window_returned(self):
        window = ContextWindow(minutes=120)
        inside  = make_msg("inside",  "2024-01-15T09:00:00")   # 60 min before → inside
        outside = make_msg("outside", "2024-01-15T07:00:00")   # 180 min before → outside
        window.add(outside)
        window.add(inside)
        result = window.get_recent("2024-01-15T10:00:00")
        ids = {m.message_id for m in result}
        assert ids == {"inside"}


# ---------------------------------------------------------------------------
# Current message not in its own context
# ---------------------------------------------------------------------------

class TestCurrentMessageExclusion:
    def test_get_recent_before_add_excludes_current(self):
        """Canonical usage: get_recent() called before add()."""
        window = ContextWindow()
        prior = make_msg("prior", "2024-01-15T09:50:00")
        current = make_msg("current", "2024-01-15T10:00:00")

        window.add(prior)
        context = window.get_recent(before_ts=current.timestamp)
        window.add(current)

        ids = {m.message_id for m in context}
        assert "current" not in ids
        assert "prior" in ids


# ---------------------------------------------------------------------------
# Custom minutes override
# ---------------------------------------------------------------------------

class TestCustomMinutes:
    def test_custom_minutes_narrows_window(self):
        window = ContextWindow(minutes=120)
        msg_60min = make_msg("m_60", "2024-01-15T09:00:00")   # 60 min before 10:00
        msg_90min = make_msg("m_90", "2024-01-15T08:30:00")   # 90 min before 10:00

        window.add(msg_60min)
        window.add(msg_90min)

        # With 30-minute override only m_60 should appear
        result = window.get_recent("2024-01-15T10:00:00", minutes=30)
        ids = {m.message_id for m in result}
        assert ids == set()   # 60 min > 30 min, so nothing

    def test_custom_minutes_widens_window(self):
        window = ContextWindow(minutes=30)
        msg = make_msg("m1", "2024-01-15T08:00:00")   # 120 min before 10:00
        window.add(msg)

        # Default 30-min window excludes it; 180-min override includes it
        assert window.get_recent("2024-01-15T10:00:00") == []
        result = window.get_recent("2024-01-15T10:00:00", minutes=180)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

class TestOrdering:
    def test_results_preserve_insertion_order(self):
        window = ContextWindow()
        for i in range(1, 5):
            window.add(make_msg(f"m{i}", f"2024-01-15T09:{i:02d}:00"))
        result = window.get_recent("2024-01-15T10:00:00")
        ids = [m.message_id for m in result]
        assert ids == ["m1", "m2", "m3", "m4"]


# ---------------------------------------------------------------------------
# maxlen eviction
# ---------------------------------------------------------------------------

class TestMaxlen:
    def test_oldest_message_evicted_when_maxlen_reached(self):
        window = ContextWindow(maxlen=3)
        for i in range(1, 5):
            window.add(make_msg(f"m{i}", f"2024-01-15T09:{i:02d}:00"))
        # m1 should have been evicted
        assert len(window) == 3
        result = window.get_recent("2024-01-15T10:00:00")
        ids = {m.message_id for m in result}
        assert "m1" not in ids
        assert {"m2", "m3", "m4"} == ids
