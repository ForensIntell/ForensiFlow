# 脚本前置探索指导

这个阶段发生在导航完成之后、生成取证脚本之前。你的任务不是写脚本，而是通过当前 UI、完整 XML 和少量安全探索，判断页面应该用哪种提取模式，并把结构化结论写入 `workspace_context.json`。

## 工作目标

1. 读取当前 XML 摘要并保存完整 XML，理解目标页面结构。默认不要把完整 XML 全文返回给模型。
2. 判断 `extraction_pattern`。如果无法可靠判断，使用 `UNKNOWN`，不要强行猜。
3. 判断生成脚本前缺哪些上下文。
4. 必要时调用探索工具，例如 `probe_scroll_position`、少量安全滑动、点击一个样例 item 后返回。
5. 用 `update_workspace_context` 保存探索结果。
6. 用 `set_extraction_plan` 保存最终提取计划。只有 `missing_context` 基本为空后，才进入脚本生成。

## 支持的 extraction_pattern

- `STATIC_SCREEN`: 当前屏静态页面/详情页提取。适用于个人资料页、设置页、账号信息页、详情页。不需要翻页，不需要点子页面；脚本仍应按 section/block 提取 raw_components，而不是只抽固定字段。
- `SCROLL_LIST`: 单层滑动列表提取。适用于联系人列表、订单列表、账单列表、群成员列表、搜索结果列表。
- `REVERSE_TIMELINE`: 逆向时间流提取。适用于聊天记录、历史消息、通知流。通常从最新内容开始回溯更早内容。必须明确写“手指滑动方向”：如果更早内容在当前视口下方（如 Chrome 历史从顶部开始），用 `finger_up`；如果更早内容在当前视口上方（如聊天从底部最新消息开始），用 `finger_down`。
- `FORWARD_TIMELINE`: 正向时间流提取。适用于动态流、浏览记录、足迹、时间线记录。必须明确写“手指滑动方向”，不要只写“向上/向下”这种视觉描述。
- `LIST_DETAIL`: 单层列表-详情嵌套提取。适用于订单列表点详情、联系人列表点个人主页、群聊列表点群详情。
- `PAGINATED_LIST`: 分页型列表提取。适用于下一页、加载更多、页码、WebView 分页。
- `MULTI_SECTION`: 多分区 / 多 Tab / 多筛选条件提取。适用于订单状态 Tab、账单筛选、好友/群聊分栏、年份/月度筛选。
- `MULTI_LEVEL_DETAIL`: 先保留 TODO；本阶段不要强行实现多层嵌套。
- `UNKNOWN`: 无法可靠判断。

## required_context

- `STATIC_SCREEN`: `ui_observations`, `extraction_plan`
- `SCROLL_LIST`: `ui_observations`, `scroll_position`, `extraction_plan`
- `REVERSE_TIMELINE`: `ui_observations`, `scroll_position`, `extraction_plan`
- `FORWARD_TIMELINE`: `ui_observations`, `scroll_position`, `extraction_plan`
- `LIST_DETAIL`: `ui_observations`, `scroll_position`, `extraction_plan`, `item_schema` 或 `nested_flow_map`
- `PAGINATED_LIST`: `ui_observations`, `extraction_plan`, `pagination_state`
- `MULTI_SECTION`: `ui_observations`, `extraction_plan`, `section_map`

## 可用探索动作

- `read_latest_ui_xml {}`: 保存当前完整 XML 到工作区，默认只返回路径和摘要。此工具只用于 mark_navigation_complete 后的探索/脚本阶段；导航阶段每步已有自动简化 ui_state。只有需要小段精确结构时才使用 `include_content=true`，且保持较小 `content_limit`。
- `probe_scroll_position {scale?,duration?}`: 做短距离双向手指滑动探测，直接返回 `is_top`、`is_bottom`、`is_scrollable`，并尝试恢复探测前位置；自动写入 `scroll_position`。
- `update_workspace_context {...}`: 合并写入结构化探索结果。
- `read_workspace_context {}`: 读取当前 `workspace_context.json`。
- `set_extraction_plan {...}`: 保存最终计划。上下文满足后 runtime 会进入脚本阶段。
- 普通导航动作仍可用：`tap`, `swipe`, `press_back`, `wait`, `scroll_to_top`, `scroll_to_bottom`。

## 导航完成边界

- 只有当前页已经是实际数据提取页，才应该 `mark_navigation_complete`。
- 看到入口项不等于导航完成。例如：
  - 看到某个聊天条目，只说明可以进入聊天；不说明已到聊天记录页。
  - 看到联系人列表项，只说明可以进入联系人详情；不说明已到联系人信息页。
  - 看到订单列表项，只说明可以进入订单详情；不说明已到订单详情页。
- 聊天记录任务必须进入聊天详情页后再完成导航：标题/联系人名命中目标，且消息 ListView/消息气泡可见。
- 如果已经过早进入 exploration 但发现当前只是入口列表，可以继续使用 tap/press_back 等导航动作进入真实目标页，然后重新 read_latest_ui_xml 和 update_workspace_context。

## 探索注意事项

- 只做少量安全探索，不要破坏数据、发送消息、删除记录、授权或修改设置。
- 调用 `read_latest_ui_xml` 后，下一步优先 `update_workspace_context`，至少写入当前页面的 `ui_observations`、`extraction_inference` 和 `script_generation_todo`。不要只把结论放在自然语言上下文里。`ui_observations` 是当前页面的一次完整观察，不要混入上一页结论；需要固定证据时引用 `snapshot_page_xml` / `source_artifact`，`current_page_xml` 始终表示最新页面。
- 不要在 `ui_observations` 里手写或覆盖页面元字段，如 `source_artifact`、`current_page_xml`、`snapshot_page_xml`、`xml_chars`、`xml_signature`；这些由 runtime 自动写入。你只需要写页面语义、block/section schema、resource-id、风险控件和脚本计划。
- 点击样例 item 前，要确认它是只读详情入口；点击后必须用 `press_back` 返回父页面，并记录 `return_strategy`。
- 对 LIST_DETAIL，至少记录 `parent_item_schema`、`child_page_schema`、`return_strategy`、`processed_item_dedup` 中能确定的部分。
- 对 SCROLL_LIST / TIMELINE，可调用 `probe_scroll_position` 记录当前是否在顶部/底部以及页面是否可滚动。probe 已自动写入 `scroll_position`，下一步不要重复 update 同一份 scroll_position；只在需要时补充解释字段。
- 聊天类 REVERSE_TIMELINE 不依赖 probe 精确定位。计划通常写 `initial_position_strategy=scroll_to_bottom_first`，`collection_finger_swipe_direction=finger_down`，表示手指下滑获取更早消息；脚本运行时用去重和连续稳定轮次停止。
- 对任何页面，都要在 `script_generation_todo` 或 `extraction_plan.notes` 里描述语义块边界和 raw block 策略，例如消息 row、联系人 row、profile header、个人详情 section、列表 item。脚本默认应先输出 `raw_components`，再做 `normalized_fields` 归类；不要只列固定字段白名单。
- runtime 会在 swipe/scroll/probe 后比较动作前后 XML 签名，并把 `action_monitor` 写入 action result 和 `workspace_context.json`。如果 `xml_changed=false` 或 `possible_edge=true`，应记录为可能到达顶部/底部或无更多内容，不要继续盲目同向滑动。
- 对 MULTI_SECTION，记录可见 section/tab 控件、当前选中项、每个 section 是否需要单独遍历。
- 对 PAGINATED_LIST，记录下一页/加载更多按钮、页码控件、页面变化证据和结束条件。
- 如果证据不足，写 `UNKNOWN` 或保守计划，不要装作确定。

## workspace_context.json 写入要求

必须写 JSON，不写散文。推荐结构：

```json
{
  "task_goal": "用户目标",
  "ui_observations": {
    "page_type_evidence": [],
    "key_resource_ids": [],
    "visible_text_samples": [],
    "risk_controls": []
  },
  "scroll_position": {},
  "extraction_inference": {
    "extraction_pattern": "UNKNOWN",
    "confidence": 0.0,
    "evidence": []
  },
  "extraction_plan": {},
  "item_schema": {},
  "pagination_state": {},
  "section_map": {},
  "nested_flow_map": {},
  "updated_at": ""
}
```

## set_extraction_plan 示例

```json
{
  "extraction_pattern": "REVERSE_TIMELINE",
  "target": "提取示例对象的聊天记录",
  "initial_position_strategy": "scroll_to_bottom_first",
  "collection_finger_swipe_direction": "finger_down",
  "collection_scroll_direction": "finger_down",
  "scroll_direction": "finger_down",
  "required_context": ["ui_observations", "scroll_position", "extraction_plan"],
  "available_context": ["ui_observations", "scroll_position"],
  "missing_context": [],
  "page_merge_strategy": "reverse_pages_then_flatten",
  "final_output_order": "oldest_to_newest",
  "dedup_key_rules": [
    "使用日期/时间/内容或媒体标题/发送方/消息类型等语义字段",
    "禁止包含 source_bounds、scroll_index、page_index、row_index、message_index"
  ],
  "notes": [
    "当前页为聊天详情页；需要处理消息方向、时间、媒体消息和日期分隔符。",
    "REVERSE_TIMELINE 不能按屏幕采样顺序直接 append；每屏先按 bounds.y1 排序并保存到 pages，最终 reversed(pages) 后 flatten。"
  ]
}
```

## 典型流程

1. `mark_navigation_complete`
2. `read_latest_ui_xml`
3. `update_workspace_context` 写入 `ui_observations` 和初步 `extraction_inference`
4. 如果是列表或时间流，调用 `probe_scroll_position`
5. 必要时少量点击样例 item 并返回，写入 `item_schema` / `nested_flow_map`
6. `set_extraction_plan`
7. 进入脚本生成：优先 `write_script` 直接写入首版完整原型脚本，然后 `run_script`；后续修复再 `read_script`、`patch_script` 或 `replace_script_lines`
