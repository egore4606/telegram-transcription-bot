# Guided settings, diagnostics and short conversation context

## User controls

- `/start` and `/settings`: five-step setup for output mode, language/style, cleaned vs verbatim transcript, simple vs technical interface, and context consent.
- `/cancel`: discard an unfinished setup. Existing settings stay in effect until the final selection commits the complete profile.
- `/details simple` (default): no model/provider names in progress or errors.
- `/details technical`: show model identity and safe error metadata (category, exception class, numeric HTTP status), never raw SDK error bodies, credentials, URLs, request text or stack traces.
- `/context`: show current context state and privacy notice.
- `/context on`: explicitly enable short context in this private chat or group.
- `/context off`: disable and immediately clear all context buffers for this chat.
- `/context clear`: clear the buffers without changing consent.

Private and group settings are independent. All shared group setting changes, including the older language/output/style commands and setup callbacks, require a current group administrator. Callback sessions are time-limited, bounded and bound to the initiating user, chat and exact setup message. Settings survive restart; unfinished setup does not.

## Context boundaries

Context is **OFF by default**, including for all existing users and groups after migration. Enabling in a group displays a notice to that chat. It is not a feature that silently scans history.

The first accepted original voice/video note starts a small in-memory window but receives no earlier conversational context. Only human text subsequently delivered to this bot is eligible to enter that buffer. A later accepted original voice/video note can consult earlier messages if the immediately previous original media is no more than **120 seconds** old. A longer gap starts a fresh session. Messages and completed media summaries older than **300 seconds** are excluded; model completion does not reset the original message timestamp.

Buffers are isolated by `(chat ID, message thread ID)` so forum topics cannot leak into one another. Forwarded media/text, bot messages, edited updates, commands, feedback and setup input are excluded. Blocked/ignored senders are excluded again at prompt construction. Retry buttons process their historical media standalone and do not reconstruct context from the persistent processing history. Queued jobs cannot gain context from messages that arrived after their own original message.

Only compact bounded text/previous media results are held; raw media, whole chat histories and reply chains are not collected for this feature. Numeric speaker/message IDs are removed from the additional model context and replaced by local speaker labels. The buffer is not written to SQLite, logs or public artifacts. It has per-message/per-chat/global memory caps and a periodic expiry sweep. Disabling/clearing invalidates pending context tickets too. Restart drops all temporary context. Existing transcription/history persistence is unchanged; the five-minute limit is for the **additional conversation buffer**, not retroactive deletion of ordinary processing history. Clearing cannot recall a request already sent to the model service.

Selected context is sent to the same external processing service as the media.
Context is rebuilt before each new model/key attempt, including file-STT postprocessing, so disable/clear/expiry prevents resending old context on a later retry. It cannot recall a request already in flight. A timestamp or same sender is NOT sufficient semantic proof. The prompt requires an explicit topic/reply/reference connection; uncertain or unrelated context must be ignored. Context is untrusted data, not instructions, and cannot authorize tools or override the transcription task. It may clarify the meaning of a summary, but must never add words/facts not actually spoken to the transcript. This is a model instruction, not a guarantee that a generative model never makes relevance mistakes.

## Telegram visibility

Only messages actually delivered by the Bot API can be considered. Telegram privacy mode can hide ordinary group text unless the bot is an administrator or privacy mode is disabled. This release does not change BotFather settings or group privileges automatically. It also does not read messages sent by other bots. The bot's own successful media summaries are recorded directly by the processing pipeline rather than waiting to receive its own Telegram messages.

Official behavior: https://core.telegram.org/bots/faq#what-messages-will-my-bot-get

## Schema and deployment

Migration 6 adds a separate `interface_preferences` table; existing output/language/style settings and processing history remain untouched. No destructive migration or context-message database table is introduced. Back up the data volume before deployment. A rollback to schema-5 code requires the pre-upgrade database backup because older code correctly refuses a newer schema version.

The changelog is available through `/changelog`. Deployment never calls `/broadcast_changelog` or sends an automatic announcement.
