"""Offline, clock-controlled privacy and isolation tests for rolling context."""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from conversation_context import ConversationContext


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def context():
    clock = Clock()
    return ConversationContext(clock=clock), clock


def media(store, clock, message_id, user_id=10, scope=(1, 0), **kwargs):
    return store.begin_media(scope, message_id, user_id, clock.now, **kwargs)


def texts(store, ticket, **kwargs):
    return [item["text"] for item in store.snapshot(ticket, **kwargs)]


def test_first_media_opens_recording_without_reading_historical_text(context):
    store, clock = context
    store.add_text((1, 0), 1, 10, "before opt-in activation", clock.now)
    first = media(store, clock, 2)
    assert first.eligible is False
    assert store.snapshot(first) == []
    store.complete_media(first, "long transcript", "compact summary")
    clock.now += 1
    store.add_text((1, 0), 3, 20, "after activation", clock.now)
    clock.now += 1
    second = media(store, clock, 4)
    assert second.eligible is True
    assert texts(store, second) == ["compact summary", "after activation"]
    entries = store.snapshot(second)
    assert entries[0] == {
        "message_id": 2, "user_id": 10, "speaker": "user:10",
        "kind": "media", "text": "compact summary",
    }
    assert entries[1]["kind"] == "text"
    assert json.loads(json.dumps(entries)) == entries
    with pytest.raises(FrozenInstanceError):
        first.eligible = True


@pytest.mark.parametrize("gap,eligible", [(120, True), (120.001, False)])
def test_exact_followup_window_and_restart_prevents_old_text_bleed(context, gap, eligible):
    store, clock = context
    first = media(store, clock, 1)
    store.complete_media(first, "old voice", "")
    clock.now += 1
    store.add_text((1, 0), 2, 20, "old text", clock.now)
    clock.now = first.timestamp + gap
    second = media(store, clock, 3)
    assert second.eligible is eligible
    assert texts(store, second) == (["old voice", "old text"] if eligible else [])
    if not eligible:
        store.complete_media(first, "late result", "late summary")
        store.complete_media(second, "new voice", "")
        clock.now += 1
        third = media(store, clock, 4)
        assert texts(store, third) == ["new voice"]


def test_chat_and_topic_scopes_are_isolated(context):
    store, clock = context
    scopes = [(1, 0), (1, 5), (2, 0)]
    for scope in scopes:
        first = media(store, clock, 1, scope=scope)
        store.complete_media(first, str(scope), "")
    clock.now += 1
    for scope in scopes:
        second = media(store, clock, 2, scope=scope)
        assert texts(store, second) == [str(scope)]


def test_forwarded_media_neither_reads_nor_creates_or_updates_context(context):
    store, clock = context
    forwarded = media(store, clock, 1, forwarded=True)
    store.complete_media(forwarded, "foreign speaker", "foreign summary")
    store.add_text((1, 0), 2, 10, "not activated", clock.now)
    assert store.snapshot(forwarded) == []
    first = media(store, clock, 3)
    assert first.eligible is False
    store.complete_media(first, "local voice", "")
    clock.now += 100
    forwarded = media(store, clock, 4, forwarded=True)
    assert store.snapshot(forwarded) == []
    store.complete_media(forwarded, "foreign voice", "")
    clock.now += 21
    second = media(store, clock, 5)
    assert second.eligible is False  # forwarded media did not bridge the 120s gap
    store.complete_media(second, "fresh local", "")
    clock.now += 1
    assert texts(store, media(store, clock, 6)) == ["fresh local"]


@pytest.mark.parametrize("age", [300.001, -0.001, float("inf"), float("nan")])
def test_backlog_future_and_invalid_timestamps_do_not_start_recording(context, age):
    store, clock = context
    invalid = store.begin_media((1, 0), 1, 10, clock.now - age)
    store.complete_media(invalid, "never stored", "")
    store.add_text((1, 0), 2, 20, "not recorded", clock.now)
    assert store.snapshot(invalid) == []
    assert len(store) == 0
    assert media(store, clock, 3).eligible is False


def test_300_second_boundary_and_late_completion_never_refresh_ttl(context):
    store, clock = context
    first = media(store, clock, 1)
    clock.now += 120
    second = media(store, clock, 2)
    clock.now = first.timestamp + 300
    store.complete_media(first, "late transcript", "")
    assert texts(store, second) == ["late transcript"]
    clock.now += 0.001
    store.purge()
    assert texts(store, second) == []
    store.complete_media(first, "resurrection", "")
    assert texts(store, second) == []
    clock.now = second.timestamp + 300.001
    assert store.snapshot(second) == []
    assert len(store) == 0


def test_backlog_at_exact_300_boundary_expires_at_original_timestamp(context):
    store, clock = context
    ticket = store.begin_media((1, 0), 1, 10, clock.now - 300)
    assert len(store) == 1
    clock.now += 0.001
    store.complete_media(ticket, "expired", "")
    assert len(store) == 0


@pytest.mark.parametrize("operation", ["clear", "clear_chat", "clear_all"])
def test_clear_invalidates_pending_tickets_even_when_scope_recreated(context, operation):
    store, clock = context
    first = media(store, clock, 1)
    clock.now += 1
    old = media(store, clock, 2)
    if operation == "clear":
        store.clear((1, 0))
    elif operation == "clear_chat":
        store.clear_chat(1)
    else:
        store.clear_all()
    fresh = media(store, clock, 3)
    assert fresh.epoch != first.epoch
    assert fresh.eligible is False
    store.complete_media(old, "disabled result", "")
    assert store.snapshot(old) == []
    clock.now += 1
    assert store.snapshot(media(store, clock, 4)) == []


def test_clear_chat_removes_all_topics_but_not_other_chats(context):
    store, clock = context
    for scope in [(1, 0), (1, 4), (2, 0)]:
        ticket = media(store, clock, 1, scope=scope)
        store.complete_media(ticket, str(scope), "")
    store.clear_chat(1)
    assert len(store) == 1
    clock.now += 1
    assert media(store, clock, 2).eligible is False
    assert media(store, clock, 2, scope=(1, 4)).eligible is False
    assert texts(store, media(store, clock, 2, scope=(2, 0))) == ["(2, 0)"]


def test_concurrent_out_of_order_completions_never_include_target_or_later_messages(context):
    store, clock = context
    first = media(store, clock, 1)
    clock.now += 1
    second = media(store, clock, 2)
    clock.now += 1
    store.add_text((1, 0), 3, 20, "later reply", clock.now)
    third = media(store, clock, 4)
    store.complete_media(third, "third voice", "")
    store.complete_media(second, "second voice", "")
    store.complete_media(first, "first voice", "")
    assert texts(store, second) == ["first voice"]
    assert texts(store, third) == ["first voice", "second voice", "later reply"]
    assert store.snapshot(first) == []


def test_same_timestamp_uses_message_id_to_exclude_later_replies(context):
    store, clock = context
    first = media(store, clock, 10)
    store.complete_media(first, "first", "")
    store.add_text((1, 0), 9, 20, "before first", clock.now)
    store.add_text((1, 0), 11, 20, "preceding", clock.now)
    target = media(store, clock, 12)
    store.add_text((1, 0), 13, 20, "after target", clock.now)
    assert texts(store, target) == ["first", "preceding"]


def test_allowed_user_policy_applies_to_text_and_media_and_snapshot_is_a_copy(context):
    store, clock = context
    first = media(store, clock, 1, user_id=10)
    store.complete_media(first, "hidden media", "")
    clock.now += 1
    store.add_text((1, 0), 2, 20, "visible", clock.now)
    target = media(store, clock, 3)
    assert texts(store, target, allowed_user=lambda user: user == 20) == ["visible"]
    snapshot = store.snapshot(target)
    snapshot[0]["text"] = "mutated"
    snapshot.clear()
    assert texts(store, target) == ["hidden media", "visible"]


@pytest.mark.parametrize("summary", [None, "", " \n "])
def test_blank_summary_falls_back_to_transcript_and_empty_content_is_omitted(context, summary):
    store, clock = context
    first = media(store, clock, 1)
    store.complete_media(first, " transcription ", summary)
    clock.now += 1
    second = media(store, clock, 2)
    store.complete_media(second, "", "")
    clock.now += 1
    assert texts(store, media(store, clock, 3)) == ["transcription"]


def test_old_future_and_pre_activation_text_are_ignored(context):
    store, clock = context
    media(store, clock, 1)
    store.add_text((1, 0), 2, 10, "future", clock.now + 1)
    store.add_text((1, 0), 3, 10, "old", clock.now - 301)
    store.add_text((1, 0), 0, 10, "before activation", clock.now)
    clock.now += 1
    assert store.snapshot(media(store, clock, 4)) == []


def test_text_and_completions_do_not_keep_session_alive(context):
    store, clock = context
    first = media(store, clock, 1)
    clock.now += 299
    store.add_text((1, 0), 2, 10, "recent text", clock.now)
    store.complete_media(first, "late completion", "")
    clock.now += 1.001
    store.purge()
    assert len(store) == 0
    assert store.snapshot(first) == []


def test_scope_entry_character_and_snapshot_bounds_are_deterministic():
    clock = Clock()
    store = ConversationContext(clock=clock, max_scopes=2, max_entries=4,
                                max_entry_chars=5, max_scope_chars=12,
                                max_snapshot_chars=7)
    first = media(store, clock, 1)
    store.complete_media(first, "aaaaaa", "")
    for message_id, value in [(2, "bbbbbb"), (3, "cccccc"), (4, "dddddd")]:
        clock.now += 1
        store.add_text((1, 0), message_id, 20, value, clock.now)
    target = media(store, clock, 5)
    result = store.snapshot(target)
    assert [item["message_id"] for item in result] == [3, 4]
    assert [item["text"] for item in result] == ["cc", "ddddd"]
    assert sum(len(item["text"]) for item in result) == 7
    clock.now += 1
    media(store, clock, 1, scope=(2, 0))
    clock.now += 1
    media(store, clock, 1, scope=(3, 0))
    assert len(store) == 2
    assert store.snapshot(target) == []
    store.complete_media(target, "evicted result", "")
    assert len(store) == 2


def test_pending_tickets_are_bounded_and_evicted_completion_cannot_return():
    clock = Clock()
    store = ConversationContext(clock=clock, max_entries=3)
    first = media(store, clock, 1)
    target = first
    for message_id in range(2, 6):
        clock.now += 1
        target = media(store, clock, message_id)
    store.complete_media(first, "evicted pending media", "")
    assert store.snapshot(target) == []


@pytest.mark.parametrize("kwargs", [
    {"max_scopes": 513}, {"max_entries": 31}, {"max_entry_chars": 2001},
    {"max_scope_chars": 12001}, {"max_snapshot_chars": 8001},
    {"max_scopes": 0}, {"max_entries": -1}, {"max_entries": 1.5},
])
def test_configuration_cannot_exceed_hard_bounds(kwargs):
    with pytest.raises(ValueError):
        ConversationContext(**kwargs)


def test_purge_removes_all_idle_scopes_and_retained_content(context):
    store, clock = context
    for chat_id in range(100):
        ticket = media(store, clock, 1, scope=(chat_id, 0))
        store.complete_media(ticket, "private fixture", "")
    assert len(store) == 100
    clock.now += 300.001
    store.purge()
    assert len(store) == 0
    store.clear_all()
    assert len(store) == 0


def test_default_scope_cap_and_eviction_cannot_resurrect_old_epoch(context):
    store, clock = context
    old = media(store, clock, 1, scope=(0, 0))
    for chat_id in range(1, 513):
        media(store, clock, 1, scope=(chat_id, 0))
    assert len(store) == 512
    fresh = media(store, clock, 2, scope=(0, 0))
    assert fresh.epoch != old.epoch
    store.complete_media(old, "evicted secret", "")
    clock.now += 1
    assert texts(store, media(store, clock, 3, scope=(0, 0))) == []


def test_default_entry_cap_includes_pending_media(context):
    store, clock = context
    first = media(store, clock, 1)
    store.complete_media(first, "evict me", "")
    for message_id in range(2, 51):
        store.add_text((1, 0), message_id, 20, str(message_id), clock.now)
    target = media(store, clock, 51)
    result = store.snapshot(target)
    assert [item["message_id"] for item in result] == list(range(22, 51))
    assert len(store._sessions[(1, 0)].entries) == 30
    store.complete_media(first, "cannot return", "")
    assert texts(store, target) == [str(value) for value in range(22, 51)]


def test_default_character_caps_also_bound_retained_memory(context):
    store, clock = context
    first = media(store, clock, 1)
    store.complete_media(first, "transcript" * 5000, "summary" * 5000)
    for message_id in range(2, 12):
        store.add_text((1, 0), message_id, 20, str(message_id % 10) * 5000, clock.now)
    target = media(store, clock, 12)
    entries = store._sessions[(1, 0)].entries
    assert sum(len(entry.text) for entry in entries) == 12000
    assert all(len(entry.text) <= 2000 for entry in entries)
    result = store.snapshot(target)
    assert [item["message_id"] for item in result] == [8, 9, 10, 11]
    assert sum(len(item["text"]) for item in result) == 8000


def test_duplicate_admission_is_idempotent_and_late_admission_is_inert(context):
    store, clock = context
    first = media(store, clock, 1)
    assert media(store, clock, 1) == first
    assert store.begin_media((1, 0), 1, 99, clock.now).epoch == 0
    clock.now += 2
    target = media(store, clock, 3)
    late = store.begin_media((1, 0), 2, 10, clock.now - 1)
    assert late.epoch == 0
    store.complete_media(late, "late history", "")
    store.complete_media(first, "first", "")
    assert texts(store, target) == ["first"]


def test_policy_errors_fail_closed(context):
    store, clock = context
    first = media(store, clock, 1)
    store.complete_media(first, "private", "")
    clock.now += 1
    target = media(store, clock, 2)

    def unavailable_policy(user_id):
        raise RuntimeError("offline policy failure")

    assert store.snapshot(target, allowed_user=unavailable_policy) == []


def test_invalid_media_does_not_restart_an_existing_live_session(context):
    store, clock = context
    first = media(store, clock, 1)
    store.complete_media(first, "local", "")
    clock.now += 1
    for timestamp in (clock.now + 1, clock.now - 301):
        invalid = store.begin_media((1, 0), 2, 20, timestamp)
        store.complete_media(invalid, "never stored", "")
    assert texts(store, media(store, clock, 3)) == ["local"]


def test_each_text_expires_from_its_own_timestamp_even_in_rolling_session(context):
    store, clock = context
    first = media(store, clock, 1)
    store.complete_media(first, "first", "")
    store.add_text((1, 0), 2, 20, "early text", clock.now)
    for message_id in range(3, 6):
        clock.now += 100
        media(store, clock, message_id)
    target = media(store, clock, 6)
    assert texts(store, target) == ["first", "early text"]
    clock.now += 0.001
    assert store.snapshot(target) == []
    # Live session remains, but no expired source content or pending tickets.
    assert len(store) == 1
    assert all(entry.timestamp > first.timestamp
               for entry in store._sessions[(1, 0)].entries)


def test_parallel_completion_is_safe_and_preserves_each_target_boundary(context):
    store, clock = context
    tickets = []
    for message_id in range(1, 21):
        tickets.append(media(store, clock, message_id))
        clock.now += 1
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(store.complete_media, ticket,
                                   str(ticket.message_id), "")
                   for ticket in reversed(tickets)]
        for future in futures:
            future.result()
    for ticket in tickets:
        assert texts(store, ticket) == [str(value) for value in range(1, ticket.message_id)]


def test_later_reply_ids_are_excluded_even_with_earlier_timestamp(context):
    store, clock = context
    first = media(store, clock, 1)
    store.complete_media(first, "source", "")
    clock.now += 2
    target = media(store, clock, 2)
    store.add_text((1, 0), 3, 20, "later reply with skewed timestamp", clock.now - 1)
    assert texts(store, target) == ["source"]
