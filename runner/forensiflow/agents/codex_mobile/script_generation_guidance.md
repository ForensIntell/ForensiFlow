# 通用脚本生成指导

这份文档是脚本阶段的通用指导，不是代码模板。不要照抄成脚本；应根据当前 `current_page.xml`、用户目标和运行结果生成完整 Python 脚本。

## 基本原则

- 脚本必须只读取证。不要点击发送、删除、拨号、支付、授权、修改设置、清空记录等高风险控件。
- 脚本必须针对当前页面结构生成，不要假设不同 App 或不同页面的 resource-id 一定相同。
- 脚本必须能独立运行，并输出 `records.json`。
- 脚本必须同时输出 `records_debug.json`。`records.json` 是干净证据结果；`records_debug.json` 是修脚本专用调试结果，必须与最终 records 一一对应，并在每条记录中保留 `_debug` provenance。
- 优先从 `FORENSIFLOW_CURRENT_UI_XML` 指向的工作区 XML 读取进入脚本阶段时的页面结构，用它设计解析逻辑；不要反复要求模型侧返回完整 XML。
- `FORENSIFLOW_CURRENT_UI_XML`、`FORENSIFLOW_CURRENT_UI_OUTLINE`、`FORENSIFLOW_WORKSPACE_CONTEXT` 由 runtime 注入，脚本应直接使用这些路径；不要把它们再拼接到当前工作目录，也不要把已存在的绝对/工作区路径改写成新的相对路径。读取 XML 失败时必须打印明确错误并优先修复路径/解析逻辑，不能静默只依赖 fallback。
- 运行时如果需要最新页面，应通过 `uiautomator2.dump_hierarchy()` 获取，而不是只依赖旧 XML。
- 出现错误时，应优先用 `edit_script` 替换完整关键函数或稳定代码块，避免小补丁叠加导致逻辑混乱。
- 首版脚本使用 runtime 提供的 raw script 写入协议整文件写入：短 JSON 只声明 `write_script_raw` 动作，完整 Python 代码放在 `<BEGIN_SCRIPT>...<END_SCRIPT>` 文本块中。不要把完整代码塞进 `write_script.content` 的 JSON 字符串；长代码经过 JSON 转义后容易损坏。`edit_script` / `patch_script` / `replace_script_lines` 只用于后续修复，不用于把空白文件一次性替换成大型脚本。

## 首版脚本写入协议

当提示中出现 `<raw_script_write_protocol>`，必须按下面格式直接输出，不要使用 tool call，也不要输出 Markdown：

```text
<AGENT_OUTPUT>
{
  "evaluation_previous_goal": "上一阶段已完成 extraction_plan，可以开始生成首版脚本。",
  "memory": "",
  "script_context": "本次将写入完整 generated_script.py。",
  "next_goal": "写入首版完整脚本",
  "action": {"write_script_raw": {"relative_path": "generated_script.py", "overwrite": true}}
}
</AGENT_OUTPUT>

<BEGIN_SCRIPT>
#!/usr/bin/env python3
# complete runnable script here
<END_SCRIPT>
```

`<BEGIN_SCRIPT>` 和 `<END_SCRIPT>` 之间必须是完整可运行 Python 文件。不要把脚本包进 JSON 字符串；也不要分段写入。

## 可用环境变量

脚本运行时 runtime 会注入：

- `FORENSIFLOW_AGENT_WORKSPACE`: 脚本工作区，`records.json` 应写到这里。
- `FORENSIFLOW_DEVICE_SERIAL`: Android 设备序列号。
- `FORENSIFLOW_TARGET`: 用户取证目标。
- `FORENSIFLOW_APP_PACKAGE`: 目标 App 包名。
- `FORENSIFLOW_CURRENT_UI_XML`: 进入脚本阶段时保存的完整 XML 路径。
- `FORENSIFLOW_CURRENT_UI_OUTLINE`: 进入脚本阶段时保存的简化 UI outline 路径。
- `FORENSIFLOW_WORKSPACE_CONTEXT`: 探索阶段保存的 `workspace_context.json` 路径，包含提取模式、滑动计划和脚本生成待办。
- `FORENSIFLOW_SCRIPT_INDEX`: runtime 自动生成的 `script_index.json` 路径。它索引当前脚本的函数、类、常量、调用关系和解析/滚动/去重/输出等重要逻辑区域，供后续诊断定位使用；采集脚本通常不需要读取它。

## 自动脚本索引

runtime 会在每次 `write_script`、`patch_script`、`replace_script_lines` 和 `run_script` 前后从当前磁盘脚本自动生成 `script_workspace/script_index.json`。这个索引不是模型总结，而是由静态解析得到的事实：

- `functions` / `classes`: 名称、起止行、参数、调用列表和 `read_hint`。
- `constants`: 模块级常量。
- `important_sections`: 按宽松关键词标记的 `parse_logic`、`scroll_logic`、`dedup_logic`、`output_logic`、`field_logic`、`device_logic`。

修复脚本时采用 opencode 风格流程：

1. 先用 `read_script_index` 找到可疑函数、行号和 `repair_targets`。
2. 如果需要定位字段名、函数名、错误文本，先用 `grep_script` 搜索，不要靠连续小片段 `read_script` 猜。
3. 用 `read_script` 读取一个足够大的窗口。不要连续读取 20-60 行的小片段；如果需要更多上下文，直接读更大的窗口。
4. 读取后优先用 `edit_script` 做 `old_string -> new_string`，并尽量把 `old_string` 设为完整函数或包含唯一首尾锚点的稳定代码块；`edit_script` 会自动尝试 exact、去行号、trim、锚点块、空白归一、缩进归一、转义归一、上下文相似匹配。
5. 只有明确知道行号且文本块难以唯一匹配时，才用 `replace_script_lines`。
6. `edit_script` / `replace_script_lines` 成功后会返回 diff、语法检查结果和 `recommended_next_action`。语法通过时下一步优先 `run_script`，不要再次读同一段脚本确认。

`edit_script` 的 `action` 必须是 JSON 对象，不能把整个动作再包成字符串。正确：

```json
{"action":{"edit_script":{"relative_path":"generated_script.py","old_string":"...","new_string":"..."}}}
```

错误：

```json
{"action":"{\"edit_script\":{\"old_string\":\"...\"}}"}
```

如果替换内容较长或包含复杂正则、f-string、多层引号，优先用 `replace_script_lines` 按行替换局部函数，避免把超长转义字符串塞进 `edit_script`。

## 推荐脚本形态

完整脚本通常应包含这些部分：

- import：`json`, `os`, `re`, `time`, `xml.etree.ElementTree as ET`, `uiautomator2 as u2`。
- 配置：工作区、设备序列号、包名、目标、输出路径、滚动次数上限、停止条件。
- XML 工具函数：读取 workspace XML、dump 当前 XML、解析 bounds、读取 text/content-desc、提取 resource-id 短名。
- 页面定位：找到目标容器、列表、详情区或当前页面根节点。
- 记录提取：默认使用“块级 raw extraction”：先把一个语义块内的 text/content-desc 全量收集到 `raw_components`，再做轻量字段归类；不要只输出预先认识的固定字段。
- 字段筛选：过滤发生在块内组件层，目的是剔除明显 UI 控件；不要把字段白名单当作唯一输出条件。归类不了的目标区域内容应保留在 `raw_components` 或 `unclassified_components`。
- 去重：使用稳定业务 key，不要把 page_index、scroll_index、row_index 这类轮次信息作为唯一去重依据。
- 滚动：只在需要遍历更多记录时滚动，并检测是否真的出现新内容。
- 输出：写 `records.json`。默认可以直接输出 `list[dict]`；如需统计再输出 `{"records": list, "metadata": object}`，metadata 只放聚合统计。
- 调试输出：写 `records_debug.json`，结构与 `records.json` 对应，但每条记录额外包含 `_debug`，用于把坏结果快速定位到脚本函数。
- stdout：打印 `visible=`, `new=`, `total=`, `stop_reason=` 等诊断信息，方便 agent 判断问题。

## Provenance Debug 输出

脚本写最终结果前，应保留一份带来源的 debug 结果：

- `records.json`: 给用户和系统复用的干净结果，不包含 `_debug`、`source_bounds`、`bounds`、`scroll_index`、`page_index`、`row_index`、`dedup_key` 等调试字段。
- `records_debug.json`: 修脚本专用结果，必须与 `records.json` 一一对应，每条记录保留最终业务字段，并增加 `_debug`。

`_debug` 至少包含：

```json
{
  "scroll_index": 0,
  "page_index": 0,
  "parser": "parse_record_block",
  "block_detector": "find_record_blocks",
  "source_resource_ids": ["row_container", "title", "subtitle"],
  "source_bounds": "[0,100][1080,220]",
  "raw_texts": ["example title", "example subtitle"]
}
```

字段说明：

- `parser`: 生成该 record 的解析函数名，例如 `parse_text_row`、`parse_history_item`、`parse_profile_section`。
- `block_detector`: 发现该 block 的函数名，例如 `find_record_blocks`、`find_message_rows`。
- `source_resource_ids`: 该 record 直接使用过的 resource-id 短名或完整 id。
- `source_bounds`: 业务 block 或主要节点 bounds。
- `raw_texts`: 进入解析函数前看到的原始 text/content-desc 样本。

推荐写法：

```python
def clean_record(record):
    record = dict(record)
    record.pop("_debug", None)
    for key in ("source_bounds", "bounds", "raw_node_signature", "page_index", "scroll_index", "row_index", "message_index", "dedup_key"):
        record.pop(key, None)
    return record

def write_outputs(records, metadata=None):
    metadata = metadata or {}
    records_debug = [dict(record) for record in records]
    records_clean = [clean_record(record) for record in records_debug]
    with open(os.path.join(WORKSPACE, "records_debug.json"), "w", encoding="utf-8") as f:
        json.dump({"records": records_debug, "metadata": metadata}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(WORKSPACE, "records.json"), "w", encoding="utf-8") as f:
        json.dump({"records": records_clean, "metadata": metadata}, f, ensure_ascii=False, indent=2)
```

修复质量问题时，优先看 `records_debug.json` 中异常样本的 `_debug.parser` 和 `_debug.block_detector`，再读取对应函数修复。不要在 parser 明确指向字段解析问题时先改滚动逻辑。

## XML 解析方法

- Android XML 文本通常在 `text` 或 `content-desc` 属性中。
- 控件类型在 `class` 中，如 `android.widget.TextView`, `android.view.ViewGroup`, `android.widget.ListView`。
- resource-id 常是完整形式，如 `com.whatsapp:id/message_text`，比较时可使用完整 id 或后缀。
- Android resource-id 的“短名”必须按最后一个 `/` 后面的部分提取，而不是按 `:` 提取。错误示例：`rid.split(':')[-1]` 会把 `android:id/list` 变成 `id/list`，导致永远匹配不到 `list`；正确示例：

```python
def rid_name(node):
    rid = node.get("resource-id", "")
    return rid.rsplit("/", 1)[-1] if "/" in rid else rid.rsplit(":", 1)[-1]
```

- 也可以直接使用后缀判断，例如 `rid.endswith("/message_text")` 或 `rid.endswith(":id/message_text")`；不要生成 `split(':')[-1] == "message_text"` 这类判断。
- `bounds` 格式通常为 `[x1,y1][x2,y2]`，解析后必须按 `(x1, y1, x2, y2)` 使用。计算列表高度必须用 `y2 - y1`，不能把四元组误当成 `[top, bottom]`。例如列表 bounds `[0,282][1080,2105]` 的 top 是 `282`，bottom 是 `2105`，不是 `0` 和 `282`。
- 不要只看 class。很多 App 使用大量 `ViewGroup`，必须结合 text、content-desc、bounds、resource-id、层级关系。
- 对列表页，优先找 scrollable 节点、ListView/RecyclerView，或最大可滚动容器。
- 对详情页，可能没有明确列表，应先按视觉/层级关系切出稳定 section，再从 section 中提取 raw components。

## 默认提取范式：块级 Raw Extraction

除非任务明确只要某几个字段，生成脚本应优先采用 `whatsapp_raw_extractor.py` 一类的通用思路：先切语义块，块内全量收集原始 UI 内容，再做可选归类。不要默认生成“字段白名单脚本”。

通用流程：

- **切块**：先确定记录边界。聊天页是一条消息 row；联系人页是一个联系人 row；profile/详情页是 header、统计、个人详情、好友、帖子等语义 section；历史页是一个列表 item。
- **块内业务内容收集**：遍历 block 的所有子孙节点，但只收集证据内容。raw extraction 不是“把 UI 树全量倒出来”；Button/ImageButton/toolbar/tab/menu/edit/share/search/add/filter 这类控件默认不是证据。
- **轻量过滤**：过滤明显控件、导航、编辑/添加/分享入口、图片占位、系统栏文本和空值。过滤时必须同时看 class、resource-id、text、content-desc，并先把 `[desc] xxx`、`xxx [desc: xxx]` 归一化后再判断；不要只做字符串精确匹配。
- **content-desc 谨慎使用**：`content-desc` 常是无障碍控件描述，不等于业务值。只有它属于目标业务块且不是控件描述时才进入 `raw_components`；例如通话类型、媒体说明可保留，编辑/菜单/搜索/查看全部/头像按钮应过滤。
- **软归类**：如果能从块内内容可靠推断字段，可写入 `normalized_fields`；识别不了但属于目标 block 的内容必须保留在 `raw_components`。
- **组合字段**：同一块内相邻或相关文本可以尝试组合，但组合只是增强结果，不能决定 block 是否保留。
- **输出记录**：每个 block 至少输出一条记录，包含 `entity_type`、`content_text` 或 `raw_components`、`normalized_fields`，必要时包含 `section`。不要默认输出 `breadcrumbs`、页面路径、脚本说明或来源 App 这类非证据信息。字段级记录可以作为补充，但不能替代 raw block。

推荐结构：

```python
def collect_raw_components(block_node):
    raw = {}
    for node in block_node.iter():
        class_name = node.get("class", "")
        short_class = class_name.rsplit(".", 1)[-1]
        rid = node.get("resource-id", "")
        rid_short = rid_name(node)
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        if not text and not desc:
            continue
        value = text if text else desc
        if is_control_node(short_class, rid_short, text, desc):
            continue
        if looks_like_ui_control(value):
            continue
        key = rid_short or short_class
        raw.setdefault(key, []).append(value)
    return {k: v[0] if len(v) == 1 else v for k, v in raw.items()}

def normalize_block(raw_components, section):
    # Optional best-effort normalization only.
    # This function must never decide whether the block is emitted.
    # If no reliable field can be inferred, return {} and keep raw_components.
    return {}

def make_block_record(block_node, section):
    raw_components = collect_raw_components(block_node)
    if not raw_components:
        return None
    values = flatten_values(raw_components)
    return {
        "entity_type": infer_entity_type(section, raw_components),
        "section": section,
        "content_text": " | ".join(values),
        "raw_components": raw_components,
        "normalized_fields": normalize_block(raw_components, section),
    }
```

输出示例：

```json
{
  "entity_type": "profile_section",
  "section": "个人详情",
  "content_text": "个人详情 | 出生日期 | 2005年8月25日 | 所在地",
  "raw_components": {
    "TextView": ["个人详情", "出生日期", "2005年8月25日", "所在地"]
  },
  "normalized_fields": {
    "inferred_fields": ["best-effort normalized values derived from raw_components"]
  }
}
```

这种结构允许后续再二次解析，也能覆盖未知字段、PDF/附件/媒体/新版本 UI，而不会因为没写专门匹配规则就丢失证据。

## WhatsApp 聊天 XML 解析要点

- WhatsApp 的 `android:id/list` 直接子节点常常是没有 `resource-id` 的 `android.view.ViewGroup`；真实消息容器如 `main_layout`、`sticker_root`、`document_frame`、`call_log_title`、`message_text` 往往在这些子节点的后代中。
- 因此不要只处理 `ListView` 直接子节点的 `resource-id`。应把每个 `ListView` 子节点作为候选 row，递归检查其后代是否包含 `message_text`、`sticker_root`、`document_frame`、`call_log_title`、`call_log_subtitle`、`conversation_row_date_divider` 或 `date_wrapper/date`。
- 对每个候选 row，优先用 row 的整体 `bounds.y1` 判断屏幕顺序；但不要用 row 的整体 bounds 判断发送者，因为 WhatsApp/ListView 的 row 往往横跨整屏，会导致全部消息被判成同一方。发送者必须用消息气泡或内容容器的 bounds 判断。
- 如果首屏 XML outline 明明有 `message_text`、`call_log_title`、`document_frame`、`sticker_root` 等样本，但脚本 stdout 显示 `visible=0`，这不是“没有聊天记录”，而是解析逻辑失败，必须修复解析函数后重跑。

## 聊天发送者判定

聊天类页面通用判定规则：

- 不能用整行 row/ListView child 的 bounds 判断 sender；很多聊天 UI 的 row 是 `[0,y1][screen_width,y2]`，会横跨整屏。
- 应选择真实消息气泡/内容容器的 bounds，例如包含 `message_text` 的最近气泡容器、`bubble_bg`、`main_layout`、`conversation_text_row`、`document_frame`、`sticker_root`、通话卡片容器等。
- 使用气泡或内容容器的右下角 `x2` 判定：若 `x2` 贴近消息列表或屏幕最右边，则判定为发送方；否则判定为接收方。
- 推荐阈值：先从 ListView bounds 取 `list_right`，否则用屏幕宽度；`x2 >= list_right - max(80, screen_width * 0.08)` 判定为 `sender="me"` 或 `"sent"`，否则为 `sender=target/contact/received`。
- 如果只能找到文本节点 bounds，优先向上找包含它的气泡/内容容器；找不到时才退化用文本节点 bounds。不要退化到整行 row bounds。

推荐实现：

```python
def infer_sender_from_bubble(bubble_bounds, list_bounds=None, screen_width=1080):
    if not bubble_bounds:
        return "unknown"
    x1, y1, x2, y2 = bubble_bounds
    list_right = list_bounds[2] if list_bounds else screen_width
    right_threshold = list_right - max(80, int(screen_width * 0.08))
    return "me" if x2 >= right_threshold else "contact"
```

## 记录字段建议

每条记录建议至少包含：

- `entity_type`: 记录类型，如 `chat_message`, `profile_info`, `history_item`, `contact_info`。
- `entity_name`: 目标对象或字段名。
- `content_text`: 核心内容。
- `raw_components`: 当前语义块内收集到的原始 UI 内容。对未知字段、附件、媒体、组合字段尤其重要。
- `normalized_fields`: 从 `raw_components` 里推断出的结构化字段。字段归类是增强层，不应导致原始块内容丢失。

## 字段筛选与噪声控制

脚本面对的是 UI 树，不是干净数据库。`text` / `content-desc` 里会同时出现业务信息和控件文本。过滤必须服务于 raw block extraction，而不是把脚本变成严格字段白名单：

- 保留用户目标区域内的块级原始内容。只要内容位于目标 block 内且不是明显控件，就应进入 `raw_components`；不要要求它先匹配到已知业务字段。
- 过滤按钮、tab、菜单、导航、编辑入口、添加入口、分享入口、搜索入口、筛选入口、图片占位和系统控件。例如：`添加`、`菜单`、`查看全部`、`编辑资料`、`编辑个人主页`、`搜索`、`发布快拍`、`Cover Photo`、`Profile Picture`、`首页，第1/5个选项卡`、`全部, 第1项，共3项` 这类通常只能作为页面结构证据，不应作为最终 records。
- 对 `content-desc` 要更谨慎：它经常是无障碍描述，可能描述按钮或图片，不一定是业务值。脚本必须把 `[desc] 编辑资料`、`查看全部 [desc: 查看全部]` 这类包装形式归一化后过滤。只有当它属于目标 block 且不是明显控件时才放入 `raw_components`。
- 如果某段文本只是分区标题或 tab 名称，应优先作为 `section` 或内部上下文，不要单独输出为一条 `profile_detail` / `history_item`，也不要为了它额外输出 `breadcrumbs`。
- 允许在 metadata 里记录过滤统计，例如 `candidate_count`, `filtered_control_count`, `records_count`，但不要把被过滤的控件文本写入 records。
- 禁止只用固定字段匹配作为输出条件，例如“只命中某几个预设字段才输出”。如果一个目标 block 有未识别字段，仍应保留 block 的 `raw_components`，并在 `normalized_fields` 里填可可靠推断的字段。

推荐实现：

```python
GENERIC_UI_LABELS = {"添加", "菜单", "查看全部", "Cover Photo", "Profile Picture"}
GENERIC_UI_PATTERNS = [
    re.compile(r"第\\d+/\\d+个选项卡"),
    re.compile(r"第\\d+项，共\\d+项"),
]

def looks_like_ui_control(text):
    t = re.sub(r"\\s+", " ", text or "").strip()
    t = re.sub(r"^\\[desc\\]\\s*", "", t, flags=re.I)
    t = re.sub(r"\\s*\\[desc\\s*:\\s*[^\\]]+\\]", "", t, flags=re.I).strip()
    if not t:
        return False
    return t in GENERIC_UI_LABELS or any(p.search(t) for p in GENERIC_UI_PATTERNS)

def is_control_node(short_class, rid_short, text, desc):
    class_key = (short_class or "").lower()
    rid_key = (rid_short or "").lower()
    if class_key in {"button", "imagebutton"} or class_key.endswith("button"):
        return True
    control_words = ("edit", "menu", "search", "add", "share", "filter", "tab", "button")
    if any(word in rid_key for word in control_words):
        return True
    return (bool(text) and looks_like_ui_control(text)) or (bool(desc) and looks_like_ui_control(desc))

def should_keep_component(text, block_context):
    if not text or looks_like_ui_control(text):
        return False
    # Keep components because they belong to the target block, not because they match a fixed field whitelist.
    return bool(block_context.get("inside_target_block"))
```

最终 `records.json` 面向取证信息本身，不需要输出屏幕定位或调试字段。脚本内部可以使用这些字段排序、判定 sender、过滤边缘残缺行或诊断，但写入最终 records 前必须删除：

- `source_bounds`
- `bounds`
- `raw_node_signature`
- `page_index`
- `scroll_index`
- `row_index`
- `message_index`
- `dedup_key`

如确需保留采集统计，放在 `metadata` 中用聚合值表达，不要在每条 record 里保留 bounds、breadcrumbs 或页面路径。

可按任务补充：

- 聊天：`sender`, `timestamp`, `message_type`, `date`。
- 联系人/个人信息：`raw_components`, `normalized_fields`, `section`，可额外给出 `field_name` / `field_value` 形式的派生字段。
- 历史记录：`title`, `url`, `timestamp`, `source_app`。
- 列表成员：`display_name`, `subtitle`, `status`, `identifier`。

## 去重规则

- 去重 key 必须表达同一条真实记录，而不是同一次屏幕采样。
- 默认使用全局 hash 去重：所有页面/所有滚动轮次共享同一个 `seen_hashes`，最终输出前再做一次全局 canonical hash 去重。不要只做单页去重，也不要依赖 runtime 后处理；脚本本身必须写出已去重的 `records.json`。
- 不考虑保留重复信息时，同一 hash 只保留一条代表记录；如果同一 hash 有多条候选，优先保留字段更完整、核心字段非空、时间/标题/值更完整、不是 viewport 边缘残缺行的记录，不需要另存 duplicate 记录。
- hash 输入必须是归一化后的业务内容，而不是屏幕采样信息。不要把这些字段放进去重 hash：`source_bounds`, `bounds`, `raw_node_signature`, `page_index`, `scroll_index`, `row_index`, `message_index`, `dedup_key`。这些是屏幕采样证据或采集轮次，不是真实业务身份。
- 通用 canonical hash 可优先使用：记录类型 + section/子类型/message_type + sender/source + `content_text` 或稳定化后的 `raw_components`。如果没有 `content_text`，退化为去掉证据字段后的稳定 JSON。
- 聊天消息可用：日期 + 时间 + 文本/媒体标题 + 发送方 + 消息类型。日期缺失时可退化为时间 + 文本/媒体标题 + 发送方 + 消息类型，但要在 metadata 说明。
- 历史记录可用：标题 + URL + 时间。
- 联系人/个人信息可用：section + content_text/raw_components；字段名字段值只作为已归类内容的增强。
- 去重应在每轮可见记录提取后立即做：先生成语义 key，再判断是否新增；不要先按屏幕位置或滚动轮次追加大量原始记录。
- 对没有文本的媒体/通话/贴纸记录，要用 message_type + 时间 + 发送方 + 可访问描述/资源类型构造 key，避免空内容互相覆盖。
- 如果连续多轮滚动后的语义 key 集合完全相同，应判断为没有新内容或滚动失败。

推荐脚本里实现两个阶段：

```python
def canonical_hash(record):
    ignored = {"source_bounds", "bounds", "raw_node_signature", "page_index", "scroll_index", "row_index", "message_index", "dedup_key"}
    # Prefer stable business identity: type/subtype/source + first non-empty core value.
    core_fields = ("content_text", "title", "value", "field_value", "display_name", "url")
    core = next((str(record.get(k, "")).strip() for k in core_fields if str(record.get(k, "")).strip()), "")
    identity = {
        "entity_type": record.get("entity_type", ""),
        "type": record.get("message_type") or record.get("record_type") or record.get("type") or "",
        "source": record.get("sender") or record.get("source") or record.get("field_name") or "",
        "core": core,
    }
    if not core:
        identity = {k: v for k, v in record.items() if k not in ignored and v not in ("", None, [], {})}
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).casefold().encode("utf-8")).hexdigest()

def choose_better_record(old, new):
    # Prefer records with more non-empty business fields and avoid viewport-edge partial rows.
    return new if completeness_score(new) > completeness_score(old) else old
```

采集过程中可以先用 `seen_hashes` 控制新增；最终输出前必须再对 `final_records` 做一遍 `{hash -> best_record}` 的全局去重，防止跨页、跨日期边界或半截行重复。

## REVERSE_TIMELINE 输出顺序

凡是判定为 `REVERSE_TIMELINE`、向上回溯型时间列表、聊天记录、历史消息或通知流的任务，都不能把每次屏幕采样结果直接 append 到最终 `records`。这类页面通常从最新内容开始，逐屏回溯更早内容；直接 append 会把“最新页在前、旧页在后”，且页内/跨页顺序混乱。

必须使用“页面分组 + 反转页面”的策略：

- 每次采样先解析为 `current_page_records`，不要直接写入最终 `records`。
- `current_page_records` 必须按记录主容器 `bounds.y1` 从小到大排序，保证单屏内从上到下。
- 每条记录生成 semantic `dedup_key` 后再去重；`dedup_key` 禁止包含 `source_bounds`, `scroll_index`, `page_index`, `row_index`, `message_index`。
- `source_bounds` / `bounds` 只能作为脚本内部临时字段用于排序、sender 判定和边缘过滤，不参与去重，也不能写入最终 `records.json`。
- 每屏去重后的结果保存到 `pages: list[list[record]]`。空页或完全重复页可以不加入 pages，但要计入 raw/duplicate 统计。
- 如果采集方向是从最新消息向更早消息回溯，例如先 `scroll_to_bottom_first`，再向旧消息方向滚动，则最终使用 `reversed(pages)` 后 flatten，输出 `oldest_to_newest`。
- 如果采集方向已经是从最旧到最新，则按 `pages` 原顺序 flatten，并在 metadata 说明。
- metadata 必须记录 `page_count`, `raw_count`, `unique_count`, `duplicate_count`, `page_merge_strategy`, `final_output_order`。

推荐字段值：

```json
{
  "page_merge_strategy": "reverse_pages_then_flatten",
  "final_output_order": "oldest_to_newest"
}
```

## 滚动与停止

- 脚本运行会改变页面位置。重跑前 agent 应通过 `scroll_to_bottom` 或 `scroll_to_top` 恢复任务起点。
- 术语必须统一：**页面下滑 / 向下浏览 / 查看下方内容 = 手指上滑**，坐标表现为 `start_y > end_y`；**页面上滑 / 查看上方内容 = 手指下滑**，坐标表现为 `start_y < end_y`。
- 聊天类任务通常从最新消息开始，向旧消息方向滚动。
- 历史/列表类任务通常从列表顶部开始继续浏览更早/更下面的项目，此时必须用**手指上滑**，也就是 `start_y > end_y`，让内容上移。不要把“页面向下看”误写成手指下滑。
- 滚动坐标必须在目标滚动容器内部计算。若 `bounds=(x1,y1,x2,y2)`，则 `height = y2 - y1`，`start_y/end_y` 都应落在 `[y1, y2]` 内并避开顶部/底部输入栏；不要写成 `height = bounds[1] - bounds[0]`。例如 `[0,282][1080,2105]` 做 40% 手指下滑可用 `start_y = y1 + height*0.35`, `end_y = y1 + height*0.75`，而不是在 `98->211` 这类 toolbar 区域滑动。
- `collection_scroll_direction` / `scroll_direction` 如果使用 `up`/`down`，必须表示**手指滑动方向**，不是内容移动方向，也不是“页面向下浏览”的自然语言方向。更推荐在计划和脚本注释里写 `collection_finger_swipe_direction`: `finger_up` 或 `finger_down`。
- 判断方法：在顶部 `is_top=true,is_bottom=false` 且目标是获取更早的下方列表项（如 Chrome 历史），应 `finger_up`；在底部最新消息 `is_bottom=true` 且目标是获取上方旧消息（如聊天记录），应 `finger_down`。
- 脚本执行滚动必须使用稳定的中等距离，不要过快也不要过慢。通用默认值：单次手指滑动距离为可滚动区域高度的 40%，允许范围 25%-55%；`duration=0.25s`，允许范围 0.20-0.30s；每次滑动后 `sleep(0.5s)` 再 dump XML/解析页面，允许范围 0.4-0.8s。
- 普通列表、历史记录、通话记录：默认滑动距离为列表可视高度的 40%-50%，推荐 40%；页面重或加载慢时降到 30%-35%，并把滑动后等待提高到 0.8-1.2s。
- 聊天记录 / `REVERSE_TIMELINE` 默认使用中等偏小滑动，保证相邻页面有明显重叠，避免大幅滑动漏过短消息或半屏消息。默认滑动距离为消息列表可视高度的 35%-40%，推荐 40%，`duration=0.25s`，滑动后等待 0.5-0.8s。
- 除非是明确的 `scroll_to_top` / `scroll_to_bottom` 恢复起点动作，否则单次采集滑动距离不得超过可滚动区域高度的 55%。禁止把接近全屏的大幅滑动作为默认采集策略。
- 当前常见 1080x2400 设备、WhatsApp 消息列表约 `[0,282][1080,2105]` 时，固定坐标可用：
  - 手指下滑获取更早消息：`d.swipe(540, 850, 540, 1500, duration=0.25)`
  - 手指上滑回到更新消息：`d.swipe(540, 1500, 540, 850, duration=0.25)`
- 如果能从 XML 解析到 ListView bounds，应按列表 bounds 动态计算滑动坐标。聊天从底部回溯旧消息时，手指下滑获取更早消息：

```python
list_top, list_bottom = 282, 2105  # replace with parsed ListView bounds when available
list_h = list_bottom - list_top
start_y = int(list_top + list_h * 0.35)
end_y = int(list_top + list_h * 0.75)
d.swipe(540, start_y, 540, end_y, duration=0.25)
time.sleep(0.5)
```

历史/列表从顶部继续获取下方更早项目时，必须反过来手指上滑：

```python
list_top, list_bottom = 282, 2105
list_h = list_bottom - list_top
start_y = int(list_top + list_h * 0.75)
end_y = int(list_top + list_h * 0.35)
d.swipe(540, start_y, 540, end_y, duration=0.25)
time.sleep(0.5)
```

- 如果必须加大滑动距离或降低等待时间，应在 metadata 说明原因，并确保没有跳过短记录、半屏记录或加载中的记录。
- 不要只靠固定 `MAX_SCROLLS` 成功结束。应同时检测：
  - 连续多轮无新语义记录。
  - 页面 XML 或可见记录签名稳定。
  - 是否出现列表顶部/底部、加载完成、无更多内容等信号。
- 如果连续 2-3 次滑动后业务内容签名不变，或 `records` 不再增长，应判定可能到达边界或采集已稳定，不要继续无限滑动。
- 如果最后几轮仍持续出现新记录但触发 `max_scrolls_reached`，结果应标记为可能不完整。

## 输出契约

`records.json` 可以是：

```json
{
  "records": [],
  "metadata": {
    "raw_count": 0,
    "unique_count": 0,
    "duplicate_count": 0,
    "page_count": 0,
    "scroll_count": 0,
    "stop_reason": ""
  }
}
```

也可以直接是 `list[dict]`。如果没有必要的统计信息，优先用纯 list，减少脚本说明性噪声。

默认不要输出这些字段：

- record 内：`breadcrumbs`、`source_app`、`app`、`page_path`、`screen_path`。
- metadata 内：`target_name`、`contact_name`、`app`、`source_app`、`extraction_pattern`、`notes`、`extraction_notes`、`extracted_at`。

metadata 只放通用聚合统计，例如 `raw_count`、`unique_count`、`duplicate_count`、`page_count`、`scroll_count`、`stop_reason`。对时间线/聊天这类顺序敏感任务，确实需要说明合并顺序时，可以保留 `page_merge_strategy`、`final_output_order`；其他任务不要默认输出。

## 通用运行诊断

`run_script` 会在脚本结束后自动生成 `script_diagnostics`。这是宽松的通用诊断，不绑定具体 App 或任务，用于帮助 agent 像工程师一样定位脚本问题，而不是机械判卷。

分级含义：

- `pass`: 没发现明显结构性问题。
- `warn`: 有瑕疵但通常可交付，例如少量字段为空、可见记录因去重少于原始可见记录。
- `suspect`: 可疑，优先 inspect/patch；如果结果已经满足目标且继续修复风险更高，可说明风险后完成。
- `fail`: 明确失败，不允许 `done(success=true)`，例如脚本崩溃、`records.json` 缺失/非法、页面 XML 有明显候选数据但输出为 0。

诊断覆盖：

- 运行状态：返回码、超时、stdout/stderr。
- 解析覆盖：XML/outline 中是否有候选业务文本和 resource-id，stdout 是否报告 `visible=0`。
- 输出结构：`records.json` 是否存在、是否可解析、是否是 list 或 `{"records": list}`。
- 字段质量：通用核心字段如 `content_text/title/value/display_name/url` 是否大量为空。
- 去重质量：语义重复率、metadata 中 `raw_count/unique_count` 的重复比例。
- 全局 hash 去重质量：如果 `script_diagnostics` 出现 `global_hash_duplicates`，说明脚本输出仍有全局 canonical hash 重复；`suspect/fail` 时必须 patch 脚本去重逻辑后重跑。
- 工作区 XML 读取质量：如果出现 `workspace_xml_read_failed`，说明脚本没能读取/解析 runtime 保存的 XML。即使 live fallback 提取出了 records，也只能算带风险成功；应优先检查 `FORENSIFLOW_CURRENT_UI_XML` 路径是否被错误拼接、是否使用了 cwd 相对路径、XML 解析异常是否被静默吞掉。
- UI 噪声质量：如果出现 `generic_ui_text_noise`，说明 records 里混入较多按钮、tab、菜单、图片占位或导航标签。优先 patch 字段筛选逻辑，而不是扩大提取范围。
- 残缺记录：带 bounds 的边缘记录是否同时缺少核心字段或常见时间/标题字段。

使用规则：

- 不要因为单个 `warn` 过度修补；先判断它是否影响用户目标。
- `suspect` 默认应检查样本或修补，但可在明确说明风险后交付。
- `fail` 必须修复或重新导航/运行，不能把返回码 0 或文件存在当作成功。
- 如果诊断指出 `parser_or_filter_failed` 或 `visible_zero_with_xml_candidates`，优先检查脚本的 XML 选择器、resource-id 短名提取、候选 row 遍历和过滤条件。

## 常见问题

- 把 UI 控件当记录：如“返回”“搜索”“管理”“全部”“更多选项”。应过滤。
- 去重 key 包含滚动轮次：会把重复可见消息误判成大量新记录。
- REVERSE_TIMELINE 直接 append 每屏记录：会导致跨页顺序混乱。必须用 pages 分组，最后按采集方向反转 pages 后 flatten。
- 只提取 text 不提取 content-desc：很多 App 重要信息只在 content-desc。
- 滚动方向错误：stdout 看似每轮有记录，但语义内容一直重复。
- 空内容记录过多：应为非文本媒体补充占位或 metadata，而不是输出空字符串。
- records 只有控件文本：说明没有定位到业务节点，应重新分析 XML 层级。
- 脚本返回码 0 但 records 缺失：检查输出路径是否是 `FORENSIFLOW_AGENT_WORKSPACE/records.json`。

## 修复策略

- 解析少：重新检查 XML 中 text/content-desc/resource-id，扩大目标节点范围。
- 重复多：修正去重 key，移除 page/row/scroll index。
- 滚动无效：修正方向、滑动区域、先恢复页面起点。
- 记录噪声多：添加 UI 控件黑名单，但不要误删真实业务内容。
- 结果不完整：提高滚动上限，并增加动态停止条件。
