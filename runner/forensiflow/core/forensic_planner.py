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

### 🚨 核心能力与粒度约束（至关重要）
1. **纯界面级全量抓取**: 本系统是基于非 Root 环境下的界面自动化提取工具。当到达某个特定界面时，系统会自动执行该界面的“全量信息拉取”（包括所有可见文本、列表、节点信息）。
2. **禁止细化到特定字段**: 绝对不要在任务中指定要提取的具体字段（例如：严禁写“提取手机号、微信号、余额、用户名”）。任务规划的粒度必须是“宏观的独立界面或模块”。
3. **禁止具体动作规划**: 系统底层已封装好交互逻辑。请剥离所有“点击”、“进入”、“滑动”、“查看”等动作动词。任务描述只需指明【目标界面/模块名称】+【全量提取/遍历抓取】即可。
4. **拒绝主观分析**: 本系统仅作为“数据搬运工”。绝对禁止包含“分析”、“追踪”、“识别”、“搜索关键词”等带有逻辑推理性质的描述。
5. **任务必须标准化表达（非常重要）**：所有任务必须严格从以下“标准任务集合”中抉择并稍作应用适配，不允许自由创造新类型任务。
### 界面级任务规划参考（遵循页面隔离原则）

【通用（所有应用可能存在）】
- 账户设置/个人主页界面全量信息提取
- 应用内搜索历史列表界面遍历抓取
- 收藏/书签/关注内容列表界面全量提取
- 通知/消息提醒列表界面遍历抓取

【通讯/社交类】
- 全局联系人列表界面遍历抓取
- 好友/关注列表界面遍历抓取
- 粉丝/被关注列表界面遍历抓取
- 消息/会话总列表界面全量提取
- 聊天详情界面全量遍历抓取
- 群组/群聊列表界面遍历抓取
- 群成员列表界面全量抓取
- 通话记录界面遍历抓取
- 好友申请/添加记录界面全量提取

【金融/支付类】
- 资产总览/钱包主界面全量信息提取
- 历史交易记录/账单列表界面遍历抓取
- 交易详情界面全量信息提取
- 转账/收款记录列表界面遍历抓取
- 绑定银行卡/支付方式管理界面全量抓取
- 收款人/转账对象列表界面遍历抓取
- 优惠券/票据/账单分类界面全量提取

【购物类】
- 订单列表界面遍历抓取
- 订单详情界面全量信息提取
- 收货地址管理界面全量抓取
- 购物车界面全量信息提取
- 商品浏览历史界面遍历抓取
- 收藏商品/心愿单界面全量提取
- 客服/商家聊天界面全量抓取
- 评价/评论记录界面遍历抓取

【地图/出行类】
- 搜索历史界面遍历抓取
- 行程/订单记录界面遍历抓取
- 历史位置/足迹界面全量信息提取
- 收藏地点界面全量抓取
- 常用地址/家庭工作地址界面全量提取
- 路线规划/导航记录界面遍历抓取

## 输出格式要求

请严格按照以下JSON格式输出，不要添加任何markdown标记或其他文字。
注意：JSON字符串内部若有引用的语句，必须使用单引号（'）或中文双引号（“”），绝对禁止出现未经转义的英文双引号导致JSON解析失败！

```json
{{
  "case_analysis_summary": "案件分析摘要，说明案件类型、关键点、已识别的高价值应用",
  "forensic_plan": [
    {{
      "app_name": "应用名称",
      "package_name": "应用包名",
      "tasks": [
        "账户设置与个人主页界面全量信息提取",
        "全局联系人列表界面遍历抓取",
        "最近消息会话列表界面全量抓取"
      ]
    }}
  ]
}}
```

### 输出要求
1. case_analysis_summary: 简明扼要的案件分析，100-200字
2. app_name: 应用的完整名称
3. package_name: 必须从上述应用列表中选择正确的包名
4. tasks: 针对该应用的具体取证任务列表，每个任务要具体可执行
5. 只选择与案件相关的应用，不需要对所有应用都做规划
6. 每个应用至少2个任务，最多8个任务

现在请基于上述信息，生成取证任务规划：
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

        try:
            plan = json.loads(json_str)
        except json.JSONDecodeError as e:
            self.logger.error(f"❌ JSON解析失败: {e}")
            self.logger.error(f"原始响应: {response_text}")
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
                app_plan["tasks"] = ["通用数据提取"]

        return plan

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
        model="qwen-plus",
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
