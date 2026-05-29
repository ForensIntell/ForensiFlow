# Output Validation And Deduplication

Use this reference before declaring a run successful or when repairing diagnostics.

## records.json

Final records must be clean evidence records. Remove:

- `_debug`
- `source_bounds`, `bounds`
- `raw_node_signature`
- `page_index`, `scroll_index`, `row_index`, `message_index`
- `dedup_key`
- page paths, breadcrumbs, source app labels, script notes

Keep business fields and useful raw evidence:

- `content_text`, `text`, `title`, `name`, `value`, `message`
- `entity_type`, `message_type`, `sender`, `time`, `date`
- `raw_components`, `normalized_fields`

## records_debug.json

Must map one-to-one to final records. Each debug record contains final business fields plus `_debug`:

```json
{
  "content_text": "...",
  "_debug": {
    "scroll_index": 0,
    "page_index": 0,
    "parser": "parse_message_row",
    "block_detector": "find_message_rows",
    "source_resource_ids": ["message_text", "date"],
    "source_bounds": "[0,100][1080,220]",
    "raw_texts": ["hello", "23:12"]
  }
}
```

## Global Dedup

Scripts must deduplicate themselves. Runtime diagnostics are not a substitute.

- Use one global `seen_hashes` across all pages/scrolls.
- Hash normalized business content only.
- Exclude sampling/provenance fields: bounds, source signatures, page/scroll/row/message indexes, dedup_key.
- Prefer the best representative record when duplicates exist: more complete fields, non-empty core field, not a viewport-edge fragment.
- Run final global dedup again before writing files.

Minimal approach:

```python
IGNORED = {"_debug", "source_bounds", "bounds", "raw_node_signature", "page_index", "scroll_index", "row_index", "message_index", "dedup_key"}

def canonical_record(record):
    return {k: v for k, v in record.items() if k not in IGNORED and v not in ("", None, [], {})}
```

## REVERSE_TIMELINE Ordering

For chats or reverse timelines:

1. Extract current visible page records.
2. Sort each page by `bounds.y1` top-to-bottom.
3. Dedup semantically while collecting.
4. Store page records as `pages.append(current_page_records)`.
5. If collecting from latest toward older content, output `flatten(reversed(pages))`.

Do not directly append each screen to final records.

## Diagnostics Interpretation

- `records_missing`: script did not write output; inspect stderr.
- `records_debug_missing` or parse error: patch output logic first.
- `empty_core_fields`: add `content_text` or meaningful core fields; do not only output `content`.
- `global_hash_duplicates`: patch dedup function and rerun.
- `debug_fields_in_output`: clean final records before writing `records.json`.
- `generic_ui_text_noise`: improve control filtering.
