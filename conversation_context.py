"""Opt-in, bounded in-memory context; no persistence, logging, or history reads.

The caller MUST gate *every* entry point on the scope's opt-in setting, exclude
bots/commands/forwarded text, and call ``clear`` when disabling a scope. Merely
constructing this store records nothing. A local accepted voice/video starts a
session, but only its subsequent media within 120 seconds can read context.
Text never activates or prolongs a session. Forwarded media is always standalone.

Methods are synchronous and protected by a lock, so tickets may safely complete
out of order. Media admission is chronological per scope (timestamp, message ID);
late admission behind an already accepted media is ignored, not backfilled.
Snapshots are fresh copies of untrusted source text, not evidence of semantic
relation. Prompts must independently require clear relevance and never infer
unheard speech from context, speaker identity, or timing alone.
"""
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from threading import RLock

Scope = tuple[int, int]
RETENTION_SECONDS = 300
FOLLOWUP_SECONDS = 120
MAX_SCOPES = 512
MAX_ENTRIES = 30
MAX_ENTRY_CHARS = 2000
MAX_SCOPE_CHARS = 12000
MAX_SNAPSHOT_CHARS = 8000


@dataclass(frozen=True, slots=True)
class ContextTicket:
    """Immutable admission token; epoch zero denotes rejected/forwarded media.

    ``eligible=False`` on a valid first media still permits completion to seed
    the next media. A ticket is not a frozen snapshot: completion order may add
    earlier media, but can never add the target or messages after it.
    """

    scope: Scope
    epoch: int
    message_id: int
    timestamp: float
    eligible: bool
    user_id: int


@dataclass(frozen=True, slots=True, repr=False)
class _Entry:
    message_id: int
    user_id: int
    timestamp: float
    kind: str
    text: str = ""
    ticket: ContextTicket | None = None

    @property
    def key(self) -> tuple[float, int]:
        return self.timestamp, self.message_id


@dataclass(slots=True, repr=False)
class _Session:
    epoch: int
    started_key: tuple[float, int]
    last_media_key: tuple[float, int]
    entries: list[_Entry] = field(default_factory=list)


class ConversationContext:
    """Per-(chat_id, thread_id) rolling context with hard upper bounds.

    Limits may be reduced for a deployment, but never raised above the module
    constants. Bounds include pending media placeholders, so slow completions
    cannot create an unbounded queue. All time comparisons use the injected wall
    clock; messages exactly 300 seconds old and followups exactly 120 seconds
    apart are valid. Text and completion never refresh any media timestamp.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        max_scopes: int = MAX_SCOPES,
        max_entries: int = MAX_ENTRIES,
        max_entry_chars: int = MAX_ENTRY_CHARS,
        max_scope_chars: int = MAX_SCOPE_CHARS,
        max_snapshot_chars: int = MAX_SNAPSHOT_CHARS,
    ) -> None:
        limits = (
            (max_scopes, MAX_SCOPES),
            (max_entries, MAX_ENTRIES),
            (max_entry_chars, MAX_ENTRY_CHARS),
            (max_scope_chars, MAX_SCOPE_CHARS),
            (max_snapshot_chars, MAX_SNAPSHOT_CHARS),
        )
        if any(type(value) is not int or not 1 <= value <= ceiling
               for value, ceiling in limits):
            raise ValueError("context limits must be positive integers within hard bounds")
        self._clock = clock
        self._max_scopes = max_scopes
        self._max_entries = max_entries
        self._max_entry_chars = max_entry_chars
        self._max_scope_chars = max_scope_chars
        self._max_snapshot_chars = max_snapshot_chars
        self._sessions: dict[Scope, _Session] = {}
        self._epoch = 0
        self._lock = RLock()

    def __len__(self) -> int:
        """Number of live scopes (also purges expired content)."""
        with self._lock:
            self._purge(self._clock())
            return len(self._sessions)

    @staticmethod
    def _fresh(timestamp: float, now: float) -> bool:
        return (math.isfinite(timestamp) and math.isfinite(now)
                and 0 <= now - timestamp <= RETENTION_SECONDS)

    def _purge(self, now: float) -> None:
        for scope, session in list(self._sessions.items()):
            if not self._fresh(session.last_media_key[0], now):
                del self._sessions[scope]
                continue
            session.entries[:] = [entry for entry in session.entries
                                  if self._fresh(entry.timestamp, now)]
            if not session.entries:
                del self._sessions[scope]
            elif now - session.started_key[0] > RETENTION_SECONDS:
                # Keep only a synthetic activation watermark after the original
                # first-media ID expires; rolling sessions retain no old IDs.
                session.started_key = (now - RETENTION_SECONDS, -1)

    def purge(self) -> None:
        """Erase expired entries/scopes; invoke periodically even when idle."""
        with self._lock:
            self._purge(self._clock())

    def _bound(self, session: _Session) -> None:
        session.entries.sort(key=lambda entry: entry.key)
        if len(session.entries) > self._max_entries:
            del session.entries[:-self._max_entries]
        characters = sum(len(entry.text) for entry in session.entries)
        while characters > self._max_scope_chars:
            characters -= len(session.entries.pop(0).text)

    def begin_media(
        self,
        scope: Scope,
        message_id: int,
        user_id: int,
        timestamp: float,
        forwarded: bool = False,
    ) -> ContextTicket:
        """Admit opted-in local media, or return an inert rejected ticket.

        Admission starts/restarts recording, but the first ticket of an epoch
        cannot read previous context. A >120s gap drops the entire old session,
        including pending completions and its intervening text.
        """
        with self._lock:
            now = self._clock()
            self._purge(now)
            rejected = ContextTicket(scope, 0, message_id, timestamp, False, user_id)
            if forwarded or not self._fresh(timestamp, now):
                return rejected
            session = self._sessions.get(scope)
            key = timestamp, message_id
            if session is not None:
                for entry in session.entries:
                    if entry.message_id == message_id:
                        if (entry.ticket is not None and entry.timestamp == timestamp
                                and entry.user_id == user_id):
                            return entry.ticket
                        return rejected
                if key <= session.last_media_key:
                    return rejected
            eligible = (session is not None
                        and timestamp - session.last_media_key[0] <= FOLLOWUP_SECONDS)
            if session is None or not eligible:
                self._epoch += 1  # Never reset: clear/eviction cannot resurrect tickets.
                session = _Session(self._epoch, key, key)
                self._sessions[scope] = session
            ticket = ContextTicket(scope, session.epoch, message_id, timestamp,
                                   eligible, user_id)
            session.last_media_key = key
            session.entries.append(_Entry(message_id, user_id, timestamp, "media",
                                          ticket=ticket))
            self._bound(session)
            while len(self._sessions) > self._max_scopes:
                oldest = min(self._sessions,
                             key=lambda item: (self._sessions[item].last_media_key,
                                               self._sessions[item].epoch))
                del self._sessions[oldest]
            return ticket

    def add_text(
        self,
        scope: Scope,
        message_id: int,
        user_id: int,
        text: str,
        timestamp: float,
    ) -> None:
        """Capture already-filtered human text only after local activation.

        Caller excludes commands, bots, forwarded text, and opted-out scopes.
        Empty/expired/future/pre-activation/duplicate messages are not stored.
        """
        with self._lock:
            now = self._clock()
            self._purge(now)
            session = self._sessions.get(scope)
            if (session is None or not self._fresh(timestamp, now)
                    or (timestamp, message_id) <= session.started_key):
                return
            if any(entry.message_id == message_id for entry in session.entries):
                return
            value = text.strip()[:self._max_entry_chars]
            if not value:
                return
            session.entries.append(_Entry(message_id, user_id, timestamp, "text", value))
            self._bound(session)

    def complete_media(
        self, ticket: ContextTicket, transcription: str | None, summary: str | None,
    ) -> None:
        """Fill an admitted placeholder, preferring a compact summary.

        Only one bounded string is retained; transcript is used if summary is
        absent/blank. No raw media or copies of both full strings are retained.
        Evicted, cleared, restarted, forwarded, or expired tickets cannot write.
        """
        with self._lock:
            now = self._clock()
            self._purge(now)
            session = self._sessions.get(ticket.scope)
            if (session is None or session.epoch != ticket.epoch
                    or not self._fresh(ticket.timestamp, now)):
                return
            for index, entry in enumerate(session.entries):
                if entry.ticket == ticket:
                    value = ((summary or "").strip() or
                             (transcription or "").strip())[:self._max_entry_chars]
                    session.entries[index] = replace(entry, text=value)
                    self._bound(session)
                    return

    def snapshot(
        self,
        ticket: ContextTicket,
        allowed_user: Callable[[int], bool] | None = None,
    ) -> list[dict]:
        """Return chronological, JSON-serializable source entries before target.

        Every entry includes ``message_id``, ``user_id``, ``speaker`` (a stable
        ID-only label), ``kind`` and ``text``. Entries must be within 300s of both
        now and the target. The target and later replies are always excluded.
        Oldest context is dropped first; the oldest remaining string may be
        trimmed to keep the newest sources within the snapshot character cap.
        The optional per-user policy applies equally to text and media; a policy
        exception fails closed for that source. No database queries are made.
        """
        with self._lock:
            now = self._clock()
            self._purge(now)
            session = self._sessions.get(ticket.scope)
            if (not ticket.eligible or session is None or session.epoch != ticket.epoch
                    or not self._fresh(ticket.timestamp, now)):
                return []
            # Retained admission is required: evicted tickets are invalid too.
            if not any(entry.ticket == ticket for entry in session.entries):
                return []
            target_key = ticket.timestamp, ticket.message_id
            entries = [entry for entry in session.entries
                       if entry.text and entry.key < target_key
                       and entry.message_id < ticket.message_id
                       and 0 <= ticket.timestamp - entry.timestamp <= RETENTION_SECONDS]
            result: list[dict] = []
            remaining = self._max_snapshot_chars
            for entry in reversed(entries):
                if allowed_user is not None:
                    try:
                        if not allowed_user(entry.user_id):
                            continue
                    except Exception:  # noqa: BLE001, S112 - fail closed, never log user data
                        continue
                if remaining == 0:
                    break
                value = entry.text[:remaining]
                remaining -= len(value)
                result.append({"message_id": entry.message_id, "user_id": entry.user_id,
                               "speaker": f"user:{entry.user_id}", "kind": entry.kind,
                               "text": value})
            result.reverse()
            return result

    def clear(self, scope: Scope) -> None:
        """Disable/reset one scope and invalidate all its pending tickets."""
        with self._lock:
            self._sessions.pop(scope, None)

    def clear_chat(self, chat_id: int) -> None:
        """Clear every topic in a chat without affecting other chats."""
        with self._lock:
            for scope in [scope for scope in self._sessions if scope[0] == chat_id]:
                del self._sessions[scope]

    def clear_all(self) -> None:
        """Drop all content and invalidate all outstanding admissions."""
        with self._lock:
            self._sessions.clear()
