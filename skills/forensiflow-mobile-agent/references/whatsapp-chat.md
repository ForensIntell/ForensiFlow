# WhatsApp Chat Extraction

Use this reference for WhatsApp contact chat records or similar chat UIs.

## Pattern

Classify contact chat records as `REVERSE_TIMELINE`.

- If currently at bottom/latest, collect the current page first.
- Hand `finger_down` moves to older messages above.
- Use 35-40% of the message-list height per swipe, `duration=0.20-0.30`, wait 0.5-0.8s.
- Stop after 2-3 stable/no-new rounds or top reached.
- Save pages separately, then `reversed(pages)` and flatten to output `oldest_to_newest`.

Do not use unsupported patterns such as `SCROLL_AND_EXTRACT`.

## XML Structure

WhatsApp list is usually `android:id/list` / short id `list`.

Rows may be direct children without useful IDs; treat each ListView child as a candidate row and recursively inspect descendants. Relevant descendants:

- `message_text`: text message content.
- `date`: visible message time.
- `status`: sent/read status.
- `conversation_row_date_divider`: date separator.
- `sticker_root`, `media_container`: sticker/media.
- `document_frame`, `title`, `file_size`, `file_type`, `info`: document attachment.
- `outer_layout`, `call_log_title`, `call_log_subtitle`: call records.

If the outline shows these nodes but the script extracts zero records, the parser is wrong; do not conclude the chat has no records.

## Sender Detection

Never use the whole row bounds for sender. Rows often span the full screen.

Use the message bubble/content container bounds:

- Prefer closest container around `message_text`, `document_frame`, `sticker_root`, or call card.
- Use the container right edge `x2`.
- With `list_right` or screen width, `x2 >= list_right - max(80, width * 0.08)` means `sender="me"`/`sent`; otherwise `sender="contact"`/`received`.
- If only a text node is available, climb to a bubble-like ancestor; use the text node only as fallback.

## Record Shape

Use stable fields:

```json
{
  "entity_type": "chat_message",
  "message_type": "text|document|sticker|call|date_divider",
  "sender": "me|contact|system|unknown",
  "time": "23:12",
  "date": "2026年3月16日",
  "content_text": "message or attachment summary",
  "raw_components": {},
  "normalized_fields": {}
}
```

Date dividers may be records or page context; if emitted, mark `message_type="date_divider"` and avoid mixing with UI controls.

## Common Failures

- Using `split(":")[-1]` for resource IDs, producing `id/message_text`; use last `/`.
- Parsing only direct ListView children and missing descendant message nodes.
- Calling undefined helpers such as `scroll_to_top`, `swipe_up`, `get_current_xml`.
- Sorting only by visible time without date context.
- Dedup key includes bounds or scroll index.
- `records_debug.json` is a summary dict instead of per-record debug records.
