import sqlite3

import pytest

from pipeline.fetcher import Fetcher, GroupMismatchError
from pipeline.models import WhatsAppMessage
from tests.conftest import REAL_TARGET_JID, REAL_TARGET_NAME

TARGET_JID = "111111111111@g.us"
TARGET_NAME = "Wayne Desi Gals"
OTHER_JID = "999999999999@g.us"


def make_fetcher(db_conn, start_after="1970-01-01T00:00:00"):
    return Fetcher(db_conn, TARGET_JID, TARGET_NAME, start_after=start_after)


# ---------------------------------------------------------------------------
# validate_group
# ---------------------------------------------------------------------------

class TestValidateGroup:
    def test_correct_jid_passes(self, db_conn):
        fetcher = make_fetcher(db_conn)
        fetcher.validate_group()  # must not raise

    def test_wrong_group_name_raises(self, db_conn):
        fetcher = Fetcher(db_conn, TARGET_JID, "Wrong Name")
        with pytest.raises(GroupMismatchError, match="Wrong Name"):
            fetcher.validate_group()

    def test_unknown_jid_raises(self, db_conn):
        fetcher = Fetcher(db_conn, "000000000000@g.us", TARGET_NAME)
        with pytest.raises(GroupMismatchError, match="not found"):
            fetcher.validate_group()


# ---------------------------------------------------------------------------
# fetch_new — group isolation
# ---------------------------------------------------------------------------

class TestGroupIsolation:
    def test_returns_only_target_group_messages(self, db_conn):
        fetcher = make_fetcher(db_conn)
        messages = fetcher.fetch_new()
        jids = {m.group for m in messages}
        # group field is populated from chat_name; Other Group must never appear
        assert "Other Group" not in jids

    def test_other_group_message_never_returned(self, db_conn):
        fetcher = make_fetcher(db_conn)
        messages = fetcher.fetch_new()
        ids = {m.message_id for m in messages}
        assert "msg_011" not in ids

    def test_all_target_group_messages_returned(self, db_conn):
        fetcher = make_fetcher(db_conn)
        messages = fetcher.fetch_new()
        ids = {m.message_id for m in messages}
        expected = {f"msg_{str(i).zfill(3)}" for i in range(1, 11)}
        assert expected == ids


# ---------------------------------------------------------------------------
# fetch_new — field remapping
# ---------------------------------------------------------------------------

class TestFieldRemapping:
    def test_message_id_mapped_from_id(self, db_conn):
        fetcher = make_fetcher(db_conn)
        messages = {m.message_id: m for m in fetcher.fetch_new()}
        assert "msg_001" in messages

    def test_text_mapped_from_content(self, db_conn):
        fetcher = make_fetcher(db_conn)
        messages = {m.message_id: m for m in fetcher.fetch_new()}
        assert messages["msg_001"].text == "anyone know a good plumber near Karama? need contact number"

    def test_group_mapped_from_chat_name(self, db_conn):
        fetcher = make_fetcher(db_conn)
        messages = {m.message_id: m for m in fetcher.fetch_new()}
        assert messages["msg_001"].group == TARGET_NAME

    def test_sender_preserved(self, db_conn):
        fetcher = make_fetcher(db_conn)
        messages = {m.message_id: m for m in fetcher.fetch_new()}
        assert messages["msg_001"].sender == "Priya"

    def test_quoted_message_id_always_none(self, db_conn):
        # Go bridge schema has no quoted_message_id column; always None
        fetcher = make_fetcher(db_conn)
        messages = fetcher.fetch_new()
        assert all(m.quoted_message_id is None for m in messages)

    def test_media_type_preserved(self, db_conn):
        fetcher = make_fetcher(db_conn)
        messages = {m.message_id: m for m in fetcher.fetch_new()}
        assert messages["msg_007"].media_type == "vcard"
        assert messages["msg_008"].media_type == "image"

    def test_text_is_none_for_media_messages(self, db_conn):
        fetcher = make_fetcher(db_conn)
        messages = {m.message_id: m for m in fetcher.fetch_new()}
        assert messages["msg_007"].text is None
        assert messages["msg_008"].text is None

    def test_returns_whatsapp_message_instances(self, db_conn):
        fetcher = make_fetcher(db_conn)
        messages = fetcher.fetch_new()
        assert all(isinstance(m, WhatsAppMessage) for m in messages)


# ---------------------------------------------------------------------------
# fetch_new — watermark behaviour
# ---------------------------------------------------------------------------

class TestWatermark:
    def test_first_call_returns_all_messages(self, db_conn):
        fetcher = make_fetcher(db_conn)
        messages = fetcher.fetch_new()
        assert len(messages) == 10

    def test_second_call_returns_empty_when_no_new_messages(self, db_conn):
        fetcher = make_fetcher(db_conn)
        fetcher.fetch_new()
        second = fetcher.fetch_new()
        assert second == []

    def test_watermark_advances_to_latest_timestamp(self, db_conn):
        fetcher = make_fetcher(db_conn)
        fetcher.fetch_new()
        assert fetcher._watermark == "2024-01-15T14:05:00"

    def test_start_after_filters_earlier_messages(self, db_conn):
        # start after msg_008; should only return msg_009 and msg_010
        fetcher = make_fetcher(db_conn, start_after="2024-01-15T10:35:00")
        messages = fetcher.fetch_new()
        ids = {m.message_id for m in messages}
        assert ids == {"msg_009", "msg_010"}

    def test_same_message_not_returned_twice(self, db_conn):
        fetcher = make_fetcher(db_conn)
        first = fetcher.fetch_new()
        first_ids = {m.message_id for m in first}

        # Manually reset watermark but keep seen_ids — simulates clock edge case
        fetcher._watermark = "1970-01-01T00:00:00"
        second = fetcher.fetch_new()
        second_ids = {m.message_id for m in second}

        assert first_ids.isdisjoint(second_ids)

    def test_messages_ordered_oldest_first(self, db_conn):
        fetcher = make_fetcher(db_conn)
        messages = fetcher.fetch_new()
        timestamps = [m.timestamp for m in messages]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# Tests against real DB dump (messages_dump.sql)
# ---------------------------------------------------------------------------

class TestFetcherWithRealDump:
    def test_validate_group_passes_with_real_jid(self, db_conn_dump):
        fetcher = Fetcher(db_conn_dump, REAL_TARGET_JID, REAL_TARGET_NAME)
        fetcher.validate_group()  # must not raise

    def test_validate_group_fails_with_wrong_name(self, db_conn_dump):
        fetcher = Fetcher(db_conn_dump, REAL_TARGET_JID, "Wrong Name")
        with pytest.raises(GroupMismatchError):
            fetcher.validate_group()

    def test_fetch_returns_only_wayne_desi_gals_messages(self, db_conn_dump):
        fetcher = Fetcher(db_conn_dump, REAL_TARGET_JID, REAL_TARGET_NAME)
        messages = fetcher.fetch_new()
        assert all(m.group == REAL_TARGET_NAME for m in messages)

    def test_fetch_returns_messages(self, db_conn_dump):
        fetcher = Fetcher(db_conn_dump, REAL_TARGET_JID, REAL_TARGET_NAME)
        messages = fetcher.fetch_new()
        assert len(messages) > 0

    def test_fetch_no_duplicates(self, db_conn_dump):
        fetcher = Fetcher(db_conn_dump, REAL_TARGET_JID, REAL_TARGET_NAME)
        messages = fetcher.fetch_new()
        ids = [m.message_id for m in messages]
        assert len(ids) == len(set(ids))

    def test_fetch_second_call_returns_empty(self, db_conn_dump):
        fetcher = Fetcher(db_conn_dump, REAL_TARGET_JID, REAL_TARGET_NAME)
        fetcher.fetch_new()
        second = fetcher.fetch_new()
        assert second == []

    def test_fetch_ordered_oldest_first(self, db_conn_dump):
        fetcher = Fetcher(db_conn_dump, REAL_TARGET_JID, REAL_TARGET_NAME)
        messages = fetcher.fetch_new()
        timestamps = [m.timestamp for m in messages]
        assert timestamps == sorted(timestamps)

    def test_all_quoted_message_ids_are_none(self, db_conn_dump):
        fetcher = Fetcher(db_conn_dump, REAL_TARGET_JID, REAL_TARGET_NAME)
        messages = fetcher.fetch_new()
        assert all(m.quoted_message_id is None for m in messages)

    def test_required_fields_always_populated(self, db_conn_dump):
        fetcher = Fetcher(db_conn_dump, REAL_TARGET_JID, REAL_TARGET_NAME)
        messages = fetcher.fetch_new()
        for m in messages:
            assert m.message_id
            assert m.timestamp
            assert m.sender
            assert m.group == REAL_TARGET_NAME
