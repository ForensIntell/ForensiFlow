# Task Patterns And Exploration

Use only these `extraction_pattern` values:

- `STATIC_SCREEN`: Current screen/detail extraction. No scrolling or child pages needed.
- `SCROLL_LIST`: Single-level scrolling list such as contacts, orders, bills, search results, group members.
- `REVERSE_TIMELINE`: Reverse chronological stream such as chats, historical messages, notification streams. Usually starts near latest content and goes back to older content.
- `FORWARD_TIMELINE`: Forward/downward timeline such as history, activity, feed, browsing records.
- `LIST_DETAIL`: Parent list items must be opened into read-only detail pages, then returned.
- `PAGINATED_LIST`: Next page/load more/page number UI exists.
- `MULTI_SECTION`: Tabs, sections, filters, or multiple partitions must be traversed.
- `MULTI_LEVEL_DETAIL`: Reserved for nested flows; use only when actually supported.
- `UNKNOWN`: Evidence is insufficient.

Do not invent pattern names. If an existing context contains an unsupported name, repair it before script generation.

## Required Context

- `STATIC_SCREEN`: `ui_observations`, `extraction_plan`
- `SCROLL_LIST`: `ui_observations`, `scroll_position`, `extraction_plan`
- `REVERSE_TIMELINE`: `ui_observations`, `scroll_position`, `extraction_plan`
- `FORWARD_TIMELINE`: `ui_observations`, `scroll_position`, `extraction_plan`
- `LIST_DETAIL`: `ui_observations`, `scroll_position`, `extraction_plan`, `item_schema` or `nested_flow_map`
- `PAGINATED_LIST`: `ui_observations`, `extraction_plan`, `pagination_state`
- `MULTI_SECTION`: `ui_observations`, `extraction_plan`, `section_map`

## Navigation Boundary

Mark navigation complete only on the real data extraction page:

- Seeing an entry row is not enough.
- Chat tasks require contact/title match plus visible message list or bubbles.
- Contact tasks usually require contact detail/profile, not just a contact list row.
- Order tasks usually require order detail, not just order list.

## Exploration Rules

- Save a complete XML snapshot and a compact outline.
- Record resource IDs, semantic block boundaries, visible samples, risky controls, and scroll container bounds.
- Keep page metadata (`source_artifact`, `current_page_xml`, `snapshot_page_xml`, `xml_signature`) runtime-owned; do not handwrite it.
- Use `probe_scroll_position` or equivalent for scrollable pages, then record whether at top/bottom and whether scrollable.
- For list-detail tasks, record parent item schema, detail schema, return strategy, and processed-item dedup key.

## Chat Plan Example

```json
{
  "extraction_pattern": "REVERSE_TIMELINE",
  "initial_position_strategy": "scroll_to_bottom_first",
  "collection_finger_swipe_direction": "finger_down",
  "page_merge_strategy": "reverse_pages_then_flatten",
  "final_output_order": "oldest_to_newest",
  "dedup_key_rules": [
    "Use sender, type, date/time, content/media title/call type",
    "Never include bounds, source XML signature, page_index, scroll_index, row_index, message_index"
  ]
}
```
