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
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen3.5-27b",
        temperature: float = 0.7,
        data_dir: str = "./data"
    ):
        """
        初始化取证规划器

        Args:
            api_key: Qwen API密钥（默认从环境变量QWEN_API_KEY读取）
            base_url: API基础URL
            model: 使用的模型名称
            temperature: 温度参数
            data_dir: 数据目录
        """
        # 如果没有提供api_key，从环境变量读取
        if api_key is None:
            import os
            api_key = os.getenv("QWEN_API_KEY", "")
            if not api_key:
                raise ValueError(
                    "API密钥未提供。请通过以下方式之一提供:\n"
                    "1. 在.env文件中设置: QWEN_API_KEY=your-key\n"
                    "2. 设置环境变量: export QWEN_API_KEY='your-key'\n"
                    "3. 初始化时传入: ForensicPlanner(api_key='your-key')"
                )

        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        self.model = model
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

## 任务要求
你是一位指导自动化机器人进行取证的移动安全专家。请基于上述案件背景、取证目标和设备应用列表，制定一份取证任务规划。

====================
### 🚨 核心能力边界与约束（必须严格遵守）
====================

1. **系统能力范围**
本系统基于非 Root 环境下的界面自动化提取工具。
当到达某个目标界面时，系统会自动执行该界面的全量信息拉取（包括所有可见文本、列表、节点信息）。

2. **允许的任务智能等级**
本系统支持以下四类任务：
- Level 1：全量提取任务（面向整个应用或模块）
- Level 2：模块定向提取任务（指定某个模块或界面）
- Level 3：单对象定向提取任务（指定单个已知对象）
- Level 4：多对象/条件定向提取任务（指定多个已知对象或明确条件）

3. **禁止超出能力边界**
绝对禁止输出以下任务：
- 需要先自动寻找未知对象再决定后续步骤的任务
- 需要动态扩展关系网络的任务
- 需要边执行边重规划的任务
- 需要语义分析、证据推理、对象识别、关系发现的任务
- 例如禁止输出：“寻找与案件最相关的人”“提取 kndxx 及其相关社交网络”“自动发现可疑联系人”

4. **禁止细化到字段级**
绝对不要在任务中指定具体字段。
严禁写“提取手机号、余额、微信号、用户名、银行卡尾号”等字段级描述。
任务粒度必须保持在“界面 / 模块 / 已知对象相关界面”层面。

5. **禁止具体动作规划**
系统底层已封装好交互逻辑。
不要输出“点击、进入、滑动、查看、搜索关键词、判断、识别”等动作或策略描述。
任务描述只允许表达：
- 目标应用
- 目标界面 / 模块
- 已知对象约束
- 简单条件约束
- 全量提取 / 遍历抓取

6. **允许对象约束与条件约束**
对于已知对象、已知关系、已知范围的任务，允许输出定向提取任务。
例如允许：
- 与 kndxx 的聊天记录相关界面全量提取
- xx 与 kndxx 的聊天会话详情界面全量遍历抓取
- 与 kndxx 相关的交易记录列表界面遍历抓取
- kndxx 的个人主页/动态界面全量提取

但前提是：
- 对象必须是输入中已经明确给出的已知对象
- 任务不依赖动态探索
- 任务不依赖后续分析结果

====================
### 📚 标准任务模式（必须从这里选择）
====================

#### Level 1：全量提取任务
- 应用整体取证相关界面全量提取
- 全局联系人列表界面遍历抓取
- 消息/会话总列表界面全量提取
- 历史交易记录/账单列表界面遍历抓取
- 订单列表界面遍历抓取
- 搜索历史界面遍历抓取

#### Level 2：模块定向提取任务
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

#### Level 3：单对象定向提取任务
- 指定对象聊天会话详情界面全量遍历抓取
- 指定对象个人主页界面全量信息提取
- 指定对象动态/内容列表界面遍历抓取
- 指定对象相关交易记录列表界面遍历抓取
- 指定对象相关订单详情界面全量提取
- 指定对象相关群聊详情界面全量遍历抓取

#### Level 4：多对象/条件定向提取任务
- 指定两个对象之间的聊天会话详情界面全量遍历抓取
- 与指定对象相关的聊天记录列表界面遍历抓取
- 与指定对象相关的交易记录列表界面遍历抓取
- 包含指定对象的群聊列表界面遍历抓取
- 与指定对象相关的互动/评论记录界面遍历抓取
- 与指定对象相关的订单/行程记录界面遍历抓取

====================
### 📌 任务规划原则
====================

1. 优先选择与案件背景和取证目标高度相关的应用
2. 不需要对所有应用都规划
3. 优先输出 Level 2~Level 4 的高价值任务
4. 若案件目标较宽泛，可补充少量 Level 1 全量任务
5. 若任务中已明确给出对象或对象关系，应优先生成对应的 Level 3 或 Level 4 定向任务
6. 若缺少明确对象或条件，不要臆造对象约束任务
7. 若某任务需要先寻找未知对象、再决定下一步，则不要输出该任务

====================
### 📤 输出格式要求（严格JSON）
====================

请严格按照以下 JSON 输出，不要添加 markdown，不要添加额外解释文字。

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
### 输出字段说明
====================

1. case_analysis_summary:
- 100~200字
- 简要说明案件重点、目标对象、相关应用和推荐的取证方向

2. app_name:
- 必须使用应用列表中的完整名称

3. package_name:
- 必须从应用列表中选择正确包名

4. tasks:
- 每个应用至少 1 个任务，最多 8 个任务
- 任务必须使用上述四种等级之一
- 任务必须来自“标准任务模式”，不允许自由创造新类型任务

5. task_level:
- 只能是 1 / 2 / 3 / 4

6. task_type:
- 只能是以下四种之一：
  - full_extraction
  - module_extraction
  - targeted_object_extraction
  - conditional_extraction

7. task_description:
- 必须从标准任务模式中选择并做轻微对象适配
- 不允许自由发明任务模式

8. target_objects:
- 若为 Level 1 / Level 2，可为空数组
- 若为 Level 3，通常包含 1 个已知对象
- 若为 Level 4，通常包含 1~2 个已知对象或明确目标对象集合

9. constraint:
- 用简洁语句描述明确约束范围
- 允许写“仅针对与 kndxx 相关的聊天会话”
- 不允许写需要动态探索或分析的复杂策略

====================
### 输出前自检
====================

请检查：
- 是否只选择了与案件相关的应用
- 是否没有输出需要动态探索的任务
- 是否没有输出字段级描述
- 是否没有输出动作词
- 是否所有任务都属于 Level 1~4
- 是否 JSON 格式正确

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

            response_text = response.choices[0].message.content
            self.logger.info(f"📤 LLM原始响应:\n{response_text}\n")

            # 解析JSON响应
            plan = self._parse_plan_response(response_text)

            self.logger.info("=" * 80)
            self.logger.info("✅ 取证规划生成完成")
            self.logger.info(f"📊 涉及应用数: {len(plan['forensic_plan'])}")
            self.logger.info(f"📋 总任务数: {sum(len(app['tasks']) for app in plan['forensic_plan'])}")
            self.logger.info("=" * 80)

            return plan

        except Exception as e:
            self.logger.error(f"❌ 生成取证规划失败: {e}")
            raise

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
            output_file = self.data_dir / f"forensic_plan_{timestamp}.json"

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
    import os

    # 配置
    API_KEY = os.getenv("DASHSCOPE_API_KEY", "sk-xxx")

    planner = ForensicPlanner(
        api_key=API_KEY,
        model="qwen3.5-27b",
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
