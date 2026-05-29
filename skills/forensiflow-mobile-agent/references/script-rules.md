# Script Generation Rules

Generated scripts must be standalone Python files that can run from a ForensiFlow `script_workspace`.

## Environment Variables

Use these runtime-injected paths and values:

- `FORENSIFLOW_AGENT_WORKSPACE`: output directory; write `records.json` and `records_debug.json` here.
- `FORENSIFLOW_DEVICE_SERIAL`: Android serial for `uiautomator2.connect(serial)`.
- `FORENSIFLOW_TARGET`: user target.
- `FORENSIFLOW_APP_PACKAGE`: package name.
- `FORENSIFLOW_CURRENT_UI_XML`: saved full XML path for the page at script phase.
- `FORENSIFLOW_CURRENT_UI_OUTLINE`: saved compact outline path.
- `FORENSIFLOW_WORKSPACE_CONTEXT`: saved `workspace_context.json`.
- `FORENSIFLOW_SCRIPT_INDEX`: generated static index of the current script.

Do not join absolute env paths to the current directory. If XML reading fails, print the failed path and patch path handling.

## Allowed Runtime APIs

Use standard Python plus optional:

```python
import uiautomator2 as u2
d = u2.connect(os.environ.get("FORENSIFLOW_DEVICE_SERIAL") or None)
xml = d.dump_hierarchy()
d.swipe(x1, y1, x2, y2, duration=0.25)
```

Do not call undefined helpers such as `scroll_to_top()`, `get_current_xml()`, `is_at_bottom()`, or `swipe_up()` unless the script defines them.

## Recommended Script Shape

- Config and env loading.
- XML helpers: `read_text`, `rid_name`, `parse_bounds`, `center`, `node_text`, `iter_descendants`.
- Page/container discovery: find the target ListView/RecyclerView/section root.
- Block detection: split into semantic blocks/rows before field extraction.
- Record parsing: collect raw components first; then best-effort normalize.
- Dedup: global canonical hash across all pages/scrolls.
- Scroll collection if needed: small repeated gestures with overlap and stable stop condition.
- Output: clean `records.json`, debug `records_debug.json`, diagnostic stdout.

## Raw Block Extraction

Do not rely only on a whitelist of known fields. For each semantic block:

1. Traverse descendants.
2. Collect non-control `text` and useful `content-desc`.
3. Store evidence in `raw_components` and `content_text`.
4. Add `normalized_fields` only when reliable.

Filter obvious controls: Button/ImageButton, toolbar/menu/search/edit/share/add/filter/tab/navigation/system UI. Empty strings are not controls.

## XML Rules

- Android text is in `text` and `content-desc`.
- Resource IDs often look like `com.whatsapp:id/message_text`; short name is after the last `/`.
- Correct short ID helper:

```python
def rid_name(node):
    rid = node.get("resource-id", "")
    return rid.rsplit("/", 1)[-1] if "/" in rid else rid.rsplit(":", 1)[-1]
```

- Bounds are `[x1,y1][x2,y2]`; use `(x1, y1, x2, y2)`. Height is `y2 - y1`.

## Output Contract

`records.json` may be a list or `{"records": list, "metadata": object}`. Records should have at least one core business field such as `content_text`, `text`, `title`, `value`, `message`, `name`, or meaningful `raw_components`.

`records_debug.json` should mirror the records and add `_debug`.

Never place debug/provenance fields in final records: `_debug`, `source_bounds`, `bounds`, `raw_node_signature`, `page_index`, `scroll_index`, `row_index`, `message_index`, `dedup_key`.
