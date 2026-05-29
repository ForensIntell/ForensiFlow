"""
Forensic Planner Module - 取证规划层

该模块负责：
1. 接收案件背景和取证目标（自然语言）
2. 读取设备应用包名映射信息
3. 使用LLM生成取证任务拆分规划
4. 输出结构化的取证计划
"""

import json
import logging
import os
from typing import Dict, List, Any, Optional
from pathlib import Path
import openai

from .config import get_llm_config

# 加载.env文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 如果没有安装python-dotenv，手动读取.env文件
    env_file = Path(__file__).parent.parent.parent.parent / ".env"
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()


class ForensicPlanner:
    """取证规划器 - 使用LLM生成取证任务规划"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        data_dir: str = "./data"
    ):
        """
        初始化取证规划器

        Args:
            api_key: LLM API密钥（默认从 FORENSIFLOW/MOMI/MIMO/LLM 配置读取，兼容 PAGE_AGENT_MOBILE 旧变量）
            base_url: API基础URL
            model: 使用的模型名称
            temperature: 温度参数
            data_dir: 数据目录
        """
        llm_config = get_llm_config(api_key=api_key, api_base=base_url, model=model)

        self.client = openai.OpenAI(
            api_key=llm_config.api_key,
            base_url=llm_config.api_base
        )
        self.model = llm_config.model
        self.temperature = temperature
        self.data_dir = Path(data_dir)

        self.logger = logging.getLogger(__name__)

    def _load_app_mapping(self) -> Dict[str, Dict[str, str]]:
        """
        加载应用包名映射信息

        Returns:
            包名到应用信息的映射字典
            格式: {
                "com.whatsapp": {
                    "title": "WhatsApp Messenger",
                    "category": "通讯"
                },
                ...
            }
        """
        # 尝试从多个可能的位置加载映射文件
        possible_paths = [
            self.data_dir / "app_info" / "package_name_mapping.txt",
            self.data_dir / "app_info_cache" / "app_info_cache.json",
            Path("./data/app_info/package_name_mapping.txt"),
            Path("./data/app_info_cache/app_info_cache.json"),
        ]

        # 优先从TXT文件加载
        for path in possible_paths:
            if path.suffix == ".txt" and path.exists():
                return self._load_mapping_from_txt(path)
            elif path.suffix == ".json" and path.exists():
                return self._load_mapping_from_json(path)

        self.logger.warning(f"⚠️ 未找到应用映射文件，使用空映射")
        return {}

    def _load_mapping_from_txt(self, file_path: Path) -> Dict[str, Dict[str, str]]:
        """从TXT文件加载映射"""
        mapping = {}

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 跳过注释和空行
                    if not line or line.startswith('#') or line.startswith('='):
                        continue

                    # 解析: com.whatsapp    WhatsApp Messenger    通讯
                    parts = line.split('\t')
                    if len(parts) >= 3:
                        package_name = parts[0].strip()
                        title = parts[1].strip()
                        category = parts[2].strip()

                        mapping[package_name] = {
                            'title': title,
                            'category': category
                        }

            self.logger.info(f"✅ 从TXT加载应用映射: {len(mapping)} 个应用")
            return mapping

        except Exception as e:
            self.logger.error(f"❌ 加载TXT映射文件失败: {e}")
            return {}

    def _load_mapping_from_json(self, file_path: Path) -> Dict[str, Dict[str, str]]:
        """从JSON文件加载映射"""
        mapping = {}

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            for package_name, cache_entry in cache_data.items():
                app_info = cache_entry.get('data', cache_entry)
                mapping[package_name] = {
                    'title': app_info.get('title', ''),
                    'category': app_info.get('category', '')
                }

            self.logger.info(f"✅ 从JSON加载应用映射: {len(mapping)} 个应用")
            return mapping

        except Exception as e:
            self.logger.error(f"❌ 加载JSON映射文件失败: {e}")
            return {}

    def _format_app_list(self, app_mapping: Dict[str, Dict[str, str]]) -> str:
        """
        格式化应用列表为文本

        Args:
            app_mapping: 应用映射字典

        Returns:
            格式化的应用列表文本
        """
        lines = []
        lines.append("设备已安装应用列表:")

        # 按分类分组
        category_apps = {}
        for pkg, info in app_mapping.items():
            category = info.get('category', '未知')
            if category not in category_apps:
                category_apps[category] = []
            category_apps[category].append((pkg, info['title']))

        # 按分类输出
        for category in sorted(category_apps.keys()):
            lines.append(f"\n【{category}】")
            for pkg, title in sorted(category_apps[category]):
                lines.append(f"  - {title} ({pkg})")

        return "\n".join(lines)

    def _build_planning_prompt(
        self,
        case_background: str,
        forensic_goals: str,
        app_list_text: str
    ) -> str:
        """
        构建取证规划提示词

        Args:
            case_background: 案件背景
            forensic_goals: 取证目标
            app_list_text: 应用列表文本

        Returns:
            完整的提示词
        """
        prompt = f"""# 移动设备取证任务规划

## 案件背景
{case_background}

## 取证目标
{forensic_goals}

## 设备应用列表
{app_list_text}

你是一位指导自动化机器人执行移动设备取证任务的移动安全专家。请基于案件背景、取证目标和设备应用列表，生成一份与系统能力匹配、边界清晰、适合自动化执行的取证任务规划。

====================
### 一、系统能力边界（必须严格遵守）
====================

本系统运行于非 Root 环境下，通过界面自动化执行取证。当自动化机器人到达目标界面后，系统会自动对该界面执行全量信息拉取，包括可见文本、节点、列表项及可遍历内容。

你的职责是规划“提取哪些应用、哪些模块、哪些界面、哪些已知对象相关界面”，而不是规划具体操作过程。

你只能输出“静态可确定、无需执行中再决策”的任务。

#### 允许的任务等级
- Level 1：全量提取任务（面向整个应用或宽范围核心区域）
- Level 2：模块定向提取任务（面向指定模块、界面或功能区域）
- Level 3：单对象定向提取任务（面向输入中已明确给出的单个已知对象）
- Level 4：多对象/条件定向提取任务（面向输入中已明确给出的多个已知对象或明确条件范围）

#### 禁止输出的任务
凡符合以下任一条件，一律禁止输出：
1. 需要先发现未知对象，再决定后续任务
2. 需要根据执行中新信息动态重规划
3. 需要扩展关系网络、发现关联对象、判断可疑对象
4. 需要语义分析、证据推理、关系发现、风险判断
5. 需要细化到字段级目标，如手机号、账号、余额、卡号、订单号等
6. 需要描述具体动作或策略，如点击、进入、滑动、搜索、筛选、判断、识别等
7. 需要先搜索某关键词，再根据结果决定下一步
8. 依赖“可能、疑似、推测”等不确定条件

#### 任务描述允许包含的内容
任务描述只允许表达：
- 目标应用
- 目标模块或界面
- 已知对象约束
- 明确范围约束
- 全量提取 / 遍历抓取

#### 对象约束要求
只有当案件背景或取证目标中已经明确出现对象、对象关系或明确条件时，才允许生成 Level 3 或 Level 4 任务。
不得臆造对象，不得写“可能相关的人”“最可疑的人”等不明确对象。

====================
### 二、内部规划流程（仅用于思考，不要输出）
====================

在生成最终 JSON 前，你必须先完成以下内部判断：

1. 从案件背景和取证目标中提取：
- 已知对象
- 已知对象关系
- 已知行为/业务场景
- 已知时间范围（如有）
- 已知应用线索
- 已知证据方向

2. 从设备应用列表中筛选真正相关的应用：
- 只保留与案件目标直接相关的应用
- 不要为了凑数量纳入无关应用
- 若某应用无明确关联，可不纳入规划

3. 判断每个相关应用的任务等级：
- 应用相关但对象不明确：优先 Level 1 / Level 2
- 存在明确单一对象且应用强相关：可用 Level 3
- 存在两个明确对象或明确条件范围：可用 Level 4
- 若信息不足，不得强行生成 Level 3 / Level 4

4. 保守回退：
- 对象不明确、条件不明确、任务可能隐含动态探索时，应退回更安全的 Level 1 / Level 2
- 宁可少输出，也不要编造任务

====================
### 三、标准任务模式（优先选择，允许受控扩展）
====================

应优先从以下标准任务模式中选择任务。
若目标应用中存在与案件高度相关、但标准任务模式未覆盖的重要模块，可在不突破系统能力边界的前提下，生成“同粒度”的补充任务。

#### 受控扩展要求
补充任务必须同时满足：
1. 仍属于 Level 1 / 2 / 3 / 4 之一
2. 仍属于 full_extraction / module_extraction / targeted_object_extraction / conditional_extraction 之一
3. 粒度保持在“应用 / 模块 / 界面 / 已知对象相关界面”层面
4. 不得字段级
5. 不得包含动作词或执行策略
6. 不得依赖动态探索或执行中判断
7. 若涉及对象，对象必须来自输入中已明确给出的已知对象或明确条件

#### 标准任务模式

##### Level 1：全量提取任务
- 应用整体取证相关界面全量提取
- 全局联系人列表界面遍历抓取
- 消息/会话总列表界面全量提取
- 历史交易记录/账单列表界面遍历抓取
- 订单列表界面遍历抓取
- 搜索历史界面遍历抓取

##### Level 2：模块定向提取任务
- 账户设置/个人主页界面全量信息提取
- 群组/群聊列表界面遍历抓取
- 群成员列表界面全量抓取
- 通话记录界面遍历抓取
- 交易详情界面全量信息提取
- 收货地址管理界面全量抓取
- 收藏地点界面全量抓取
- 路线规划/导航记录界面遍历抓取
- 客服/商家聊天界面全量抓取
- 商品浏览历史界面遍历抓取
- 好友/关注列表界面遍历抓取
- 粉丝/被关注列表界面遍历抓取
- 通知/消息提醒列表界面遍历抓取

##### Level 3：单对象定向提取任务
- 指定对象聊天会话详情界面全量遍历抓取
- 指定对象个人主页界面全量信息提取
- 指定对象动态/内容列表界面遍历抓取
- 指定对象相关交易记录列表界面遍历抓取
- 指定对象相关订单详情界面全量提取
- 指定对象相关群聊详情界面全量遍历抓取

##### Level 4：多对象/条件定向提取任务
- 指定两个对象之间的聊天会话详情界面全量遍历抓取
- 与指定对象相关的聊天记录列表界面遍历抓取
- 与指定对象相关的交易记录列表界面遍历抓取
- 包含指定对象的群聊列表界面遍历抓取
- 与指定对象相关的互动/评论记录界面遍历抓取
- 与指定对象相关的订单/行程记录界面遍历抓取

#### 可接受的补充任务示例
- 钱包相关界面全量信息提取
- 卡券/票券列表界面遍历抓取
- 设备登录记录界面遍历抓取
- 草稿箱列表界面遍历抓取
- 收藏内容列表界面遍历抓取
- 云盘文件列表界面遍历抓取
- 发布记录列表界面遍历抓取

#### 不可接受的补充任务示例
- 查找最可疑联系人
- 自动识别异常交易对象
- 提取钱包余额和银行卡尾号
- 搜索包含某关键词的聊天后再决定下一步
- 点击钱包后进入账单页面并筛选最近三天记录

====================
### 四、任务生成原则
====================

1. 只选择与案件背景和取证目标高度相关的应用
2. 不需要覆盖所有应用
3. 优先输出高价值、低歧义、可直接执行的任务
4. 优先考虑 Level 2 / 3 / 4，但前提是信息足够明确
5. 没有明确对象时，不得生成对象约束任务
6. 没有明确条件时，不得生成条件约束任务
7. 案件目标较宽泛时，可补充少量 Level 1 任务兜底
8. 同一应用下任务应避免重复，尽量覆盖不同高价值模块
9. 每个应用至少 1 个任务，最多 8 个任务
10. 若某应用虽相关，但缺乏足够明确的可规划界面，可不纳入结果
11. 不得为了看起来完整而生成低价值或无依据任务

====================
### 五、输出格式要求（严格 JSON）
====================

请严格按照以下 JSON 输出，不要添加 markdown，不要添加额外解释，不要添加任何未定义字段，不要输出分析过程。

{{
  "case_analysis_summary": "案件分析摘要，说明案件重点、目标对象、相关应用和推荐的取证方向",
  "forensic_plan": [
    {{
      "app_name": "应用名称",
      "package_name": "应用包名",
      "tasks": [
        {{
          "task_level": 1,
          "task_type": "full_extraction",
          "task_description": "应用整体取证相关界面全量提取",
          "target_objects": [],
          "constraint": ""
        }},
        {{
          "task_level": 3,
          "task_type": "targeted_object_extraction",
          "task_description": "指定对象聊天会话详情界面全量遍历抓取",
          "target_objects": ["kndxx"],
          "constraint": "仅针对与 kndxx 相关的聊天会话"
        }},
        {{
          "task_level": 4,
          "task_type": "conditional_extraction",
          "task_description": "指定两个对象之间的聊天会话详情界面全量遍历抓取",
          "target_objects": ["xx", "kndxx"],
          "constraint": "仅针对 xx 与 kndxx 之间的聊天会话"
        }}
      ]
    }}
  ]
}}

====================
### 六、输出字段说明
====================

1. case_analysis_summary
- 100~200字
- 仅基于输入说明案件重点、已知对象、相关应用和推荐取证方向

2. app_name
- 必须使用设备应用列表中的完整名称

3. package_name
- 必须从设备应用列表中选择与 app_name 对应的正确包名

4. tasks
- 每个应用至少 1 个任务，最多 8 个任务
- 优先使用标准任务模式
- 若标准任务模式未覆盖目标应用的重要模块，可使用受控扩展

5. task_level
- 只能是 1 / 2 / 3 / 4

6. task_type
- 只能是以下四种之一：
  - full_extraction
  - module_extraction
  - targeted_object_extraction
  - conditional_extraction

7. task_description
- 应优先从标准任务模式中选择
- 若标准模式未覆盖目标应用的重要模块，可按受控扩展规则生成同粒度补充任务
- 不允许字段级、动作级或策略性表达
- 描述必须保持模块/界面级抽象

8. target_objects
- Level 1 / Level 2 通常为空数组
- Level 3 通常包含 1 个明确已知对象
- Level 4 通常包含 1~2 个明确对象或明确对象集合
- 所有对象必须来自案件背景或取证目标

9. constraint
- 用简洁语句描述明确边界
- 只允许静态范围约束
- 不允许动态探索逻辑、执行策略或复杂分析过程
- 若无约束，可为空字符串

====================
### 七、输出前自检
====================

输出前请检查：
- 是否只选择了与案件相关的应用
- 是否所有 app_name 都来自应用列表
- 是否所有 package_name 都与 app_name 正确对应
- 是否没有纳入明显无关应用
- 是否没有输出动态探索任务
- 是否没有输出字段级和动作级描述
- 是否没有臆造对象
- 是否在对象不足时保守回退到 Level 1 / Level 2
- 是否所有 task_level 和 task_type 都合法
- 是否所有 task_description 都保持模块/界面级粒度
- 若存在补充任务，是否仍与标准任务模式保持同粒度且未突破能力边界
- 是否每个应用的任务数量在 1~8 之间
- 是否 JSON 格式正确
- 是否没有输出任何额外字段或解释性文字

现在请基于上述信息生成取证任务规划：
"""
        return prompt

    def create_forensic_plan(
        self,
        case_background: str,
        forensic_goals: str,
        app_mapping_file: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建取证任务规划

        Args:
            case_background: 案件背景描述
            forensic_goals: 取证目标描述
            app_mapping_file: 可选的应用映射文件路径

        Returns:
            取证规划字典，包含：
            - case_analysis_summary: 案件分析摘要
            - forensic_plan: 取证任务列表
        """
        self.logger.info("=" * 80)
        self.logger.info("🔍 开始生成取证任务规划")
        self.logger.info("=" * 80)

        # 加载应用映射
        if app_mapping_file:
            app_mapping_file = Path(app_mapping_file)
            if app_mapping_file.suffix == ".txt":
                app_mapping = self._load_mapping_from_txt(app_mapping_file)
            else:
                app_mapping = self._load_mapping_from_json(app_mapping_file)
        else:
            app_mapping = self._load_app_mapping()

        if not app_mapping:
            self.logger.warning("⚠️ 应用映射为空，规划可能不准确")

        # 格式化应用列表
        app_list_text = self._format_app_list(app_mapping)

        # 构建提示词
        prompt = self._build_planning_prompt(
            case_background,
            forensic_goals,
            app_list_text
        )

        self.logger.info(f"📝 应用数量: {len(app_mapping)}")
        self.logger.info(f"🎯 取证目标: {forensic_goals[:100]}...")

        try:
            # 调用LLM生成规划
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一位资深的移动数字取证专家，精通各类移动应用的数据提取和取证分析。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=self.temperature,
                max_tokens=4000
            )

            response_text = self._extract_response_text(response)
            self.logger.info(f"📤 LLM原始响应:\n{response_text}\n")

            # 解析JSON响应
            plan = self._parse_plan_response(response_text)
            plan = self._apply_explicit_single_goal_constraint(plan, forensic_goals)

            self.logger.info("=" * 80)
            self.logger.info("✅ 取证规划生成完成")
            self.logger.info(f"📊 涉及应用数: {len(plan['forensic_plan'])}")
            self.logger.info(f"📋 总任务数: {sum(len(app['tasks']) for app in plan['forensic_plan'])}")
            self.logger.info("=" * 80)

            return plan

        except Exception as e:
            self.logger.error(f"❌ 生成取证规划失败: {e}")
            raise

    def _apply_explicit_single_goal_constraint(self, plan: Dict[str, Any], forensic_goals: str) -> Dict[str, Any]:
        """Keep demo plans narrow when the user explicitly asks for only WhatsApp chats."""
        goals = forensic_goals.lower()
        explicit_single_whatsapp_chat = (
            ("仅" in forensic_goals or "只" in forensic_goals or "only" in goals)
            and "whatsapp" in goals
            and ("聊天记录" in forensic_goals or "chat" in goals)
        )
        if not explicit_single_whatsapp_chat:
            return plan

        filtered_apps = []
        for app_plan in plan.get("forensic_plan", []):
            app_name = str(app_plan.get("app_name", ""))
            package_name = str(app_plan.get("package_name", ""))
            if "whatsapp" not in app_name.lower() and package_name != "com.whatsapp":
                continue

            chat_tasks = []
            for task in app_plan.get("tasks", []):
                desc = str(task.get("task_description", "")) if isinstance(task, dict) else str(task)
                if "消息/会话" in desc or "聊天记录" in desc or "聊天会话" in desc:
                    chat_tasks.append(task)

            if chat_tasks:
                app_copy = dict(app_plan)
                app_copy["tasks"] = chat_tasks[:1]
                filtered_apps.append(app_copy)
                break

        if filtered_apps:
            plan = dict(plan)
            plan["forensic_plan"] = filtered_apps
            self.logger.info("🎯 检测到单一 WhatsApp 聊天记录目标，已收敛为 1 个执行任务")
        return plan

    def _extract_response_text(self, response: Any) -> str:
        """兼容 OpenAI SDK 对象、dict 响应和字符串响应。"""
        if isinstance(response, str):
            return response

        if isinstance(response, dict):
            try:
                return response["choices"][0]["message"]["content"]
            except Exception:
                return json.dumps(response, ensure_ascii=False)

        try:
            return response.choices[0].message.content
        except Exception:
            return str(response)

    def _parse_plan_response(self, response_text: str) -> Dict[str, Any]:
        """
        解析LLM响应中的JSON

        Args:
            response_text: LLM响应文本

        Returns:
            解析后的规划字典
        """
        import re

        # 尝试提取JSON
        json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接查找JSON对象
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                raise ValueError("无法从响应中提取JSON")

        # 修复非标准 JSON（键名缺少双引号）
        json_str = self._fix_malformed_json(json_str)

        try:
            plan = json.loads(json_str)
        except json.JSONDecodeError as e:
            self.logger.error(f"❌ JSON解析失败: {e}")
            self.logger.error(f"原始JSON: {json_str[:500]}...")
            raise

        # 规范化任务结构，避免规划层输出形态飘移导致执行层不稳定。
        plan = self._normalize_plan_structure(plan)

        # 验证必要字段
        if "case_analysis_summary" not in plan:
            plan["case_analysis_summary"] = "案件分析摘要未生成"

        if "forensic_plan" not in plan:
            raise ValueError("响应中缺少 forensic_plan 字段")

        # 验证每个应用的字段
        for app_plan in plan["forensic_plan"]:
            if "app_name" not in app_plan:
                app_plan["app_name"] = "未知应用"
            if "package_name" not in app_plan:
                app_plan["package_name"] = "unknown"
            if "tasks" not in app_plan or not app_plan["tasks"]:
                app_plan["tasks"] = [{
                    "task_level": 1,
                    "task_type": "full_extraction",
                    "task_description": "应用整体取证相关界面全量提取",
                    "target_objects": [],
                    "constraint": ""
                }]

        return plan

    def _normalize_plan_structure(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize planner output so downstream executors can consume it predictably."""
        if not isinstance(plan, dict):
            return {"forensic_plan": []}

        normalized_plan = dict(plan)
        apps = normalized_plan.get("forensic_plan")
        if not isinstance(apps, list):
            normalized_plan["forensic_plan"] = []
            return normalized_plan

        normalized_apps = []
        for app_plan in apps:
            if not isinstance(app_plan, dict):
                continue
            normalized_app = dict(app_plan)
            normalized_app["app_name"] = str(normalized_app.get("app_name") or "未知应用").strip() or "未知应用"
            normalized_app["package_name"] = str(normalized_app.get("package_name") or "unknown").strip() or "unknown"

            tasks = normalized_app.get("tasks")
            if not isinstance(tasks, list):
                tasks = []

            normalized_tasks = []
            seen = set()
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                normalized_task = self._normalize_task(task)
                if not normalized_task:
                    continue
                task_key = (
                    normalized_task.get("task_level"),
                    normalized_task.get("task_type"),
                    normalized_task.get("task_description"),
                    tuple(normalized_task.get("target_objects") or []),
                    normalized_task.get("constraint"),
                )
                if task_key in seen:
                    continue
                seen.add(task_key)
                normalized_tasks.append(normalized_task)

            if not normalized_tasks:
                normalized_tasks = [{
                    "task_level": 1,
                    "task_type": "full_extraction",
                    "task_description": "应用整体取证相关界面全量提取",
                    "target_objects": [],
                    "constraint": ""
                }]

            normalized_app["tasks"] = normalized_tasks[:8]
            normalized_apps.append(normalized_app)

        normalized_plan["forensic_plan"] = normalized_apps
        return normalized_plan

    def _normalize_task(self, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalize a single planner task into a stable executor-friendly schema."""
        task_level = task.get("task_level", 1)
        try:
            task_level = int(task_level)
        except Exception:
            task_level = 1
        if task_level not in {1, 2, 3, 4}:
            task_level = 1

        task_type = str(task.get("task_type") or "").strip()
        allowed_types = {"full_extraction", "module_extraction", "targeted_object_extraction", "conditional_extraction"}
        if task_type not in allowed_types:
            task_type = "full_extraction" if task_level == 1 else "module_extraction"

        description = str(task.get("task_description") or "").strip()
        if not description:
            return None

        target_objects = task.get("target_objects")
        if not isinstance(target_objects, list):
            target_objects = []
        target_objects = [str(obj).strip() for obj in target_objects if str(obj).strip()]

        constraint = str(task.get("constraint") or "").strip()
        normalized = {
            "task_level": task_level,
            "task_type": task_type,
            "task_description": description,
            "target_objects": target_objects,
            "constraint": constraint,
        }

        # 保守修正：有明确对象时避免任务文本丢失对象边界。
        if target_objects and "对象" not in description and task_level in {3, 4}:
            normalized["constraint"] = constraint or f"仅针对 {', '.join(target_objects)} 相关范围"

        return normalized

    def _fix_malformed_json(self, json_str: str) -> str:
        """
        修复键名缺少双引号的 JSON

        Args:
            json_str: 原始 JSON 字符串

        Returns:
            修复后的 JSON 字符串
        """
        import re

        # 修复顶层的键（在行首的）
        json_str = re.sub(
            r'^(\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)',
            r'\1"\2"\3',
            json_str,
            flags=re.MULTILINE
        )

        # 修复嵌套的键
        json_str = re.sub(
            r'(\n\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)',
            r'\1"\2"\3',
            json_str
        )

        return json_str

    def save_plan(
        self,
        plan: Dict[str, Any],
        output_file: Optional[str] = None
    ) -> str:
        """
        保存取证规划到文件

        Args:
            plan: 取证规划字典
            output_file: 输出文件路径（可选）

        Returns:
            保存的文件路径
        """
        if output_file is None:
            timestamp = __import__('datetime').datetime.now().strftime("%Y%m%d_%H%M%S")
            plans_dir = self.data_dir / "plans"
            plans_dir.mkdir(parents=True, exist_ok=True)
            output_file = plans_dir / f"forensic_plan_{timestamp}.json"

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)

        self.logger.info(f"💾 取证规划已保存: {output_path}")
        return str(output_path)

    def print_plan(self, plan: Dict[str, Any]):
        """
        打印取证规划（可读格式）

        Args:
            plan: 取证规划字典
        """
        print("\n" + "=" * 80)
        print("📋 移动设备取证任务规划")
        print("=" * 80 + "\n")

        print("🔍 案件分析摘要")
        print("-" * 80)
        print(plan.get("case_analysis_summary", "未生成摘要"))
        print()

        print("📱 取证任务规划")
        print("-" * 80)

        for i, app_plan in enumerate(plan.get("forensic_plan", []), 1):
            print(f"\n{i}. {app_plan.get('app_name', '未知应用')} ({app_plan.get('package_name', 'unknown')})")

            tasks = app_plan.get("tasks", [])
            for j, task in enumerate(tasks, 1):
                if isinstance(task, dict):
                    level = task.get('task_level', '?')
                    desc = task.get('task_description', '')
                    objects = task.get('target_objects', [])
                    objects_str = f" [对象: {', '.join(objects)}]" if objects else ""
                    print(f"   {j}. [Level {level}] {desc}{objects_str}")
                else:
                    print(f"   {j}. {task}")

        print("\n" + "=" * 80)
        print(f"📊 统计: {len(plan.get('forensic_plan', []))} 个应用, {sum(len(app['tasks']) for app in plan.get('forensic_plan', []))} 个任务")
        print("=" * 80 + "\n")


def main():
    """测试代码"""
    llm_config = get_llm_config()

    planner = ForensicPlanner(
        api_key=llm_config.api_key,
        base_url=llm_config.api_base,
        model=llm_config.model,
        temperature=0.7
    )

    # 测试案例
    case_background = """
    2024年3月，某市公安机关接到多起报案，受害人称通过一款名为"财富宝"的APP进行投资理财，
    初期获得小额返利，后期大额投资后无法提现，平台失联。经初步统计，涉案金额超过500万元，
    受害者超过100人。犯罪嫌疑人在微信群、QQ群中推广该APP，并承诺高额回报。
    """

    forensic_goals = """
    1. 确定犯罪嫌疑人的身份信息和社交关系网络
    2. 追踪资金流向和涉案账户
    3. 提取推广活动的相关证据
    4. 识别受害者群体特征
    5. 收集诈骗过程中的聊天记录和宣传材料
    """

    # 生成规划
    plan = planner.create_forensic_plan(
        case_background=case_background,
        forensic_goals=forensic_goals
    )

    # 打印规划
    planner.print_plan(plan)

    # 保存规划
    output_file = planner.save_plan(plan)
    print(f"\n✅ 规划已保存到: {output_file}")


if __name__ == "__main__":
    main()
