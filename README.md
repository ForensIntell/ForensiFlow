# MobiAgent - 智能移动端取证自动化框架

<div align="center">

**基于 Vision-Language Model 的移动端应用自动化取证系统**

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active-success)]()

</div>

---

## 📖 项目简介

MobiAgent 是一个基于视觉语言模型（Vision-Language Model）的智能移动端应用自动化取证框架。该项目集成了先进的计算机视觉技术、自然语言处理和移动设备自动化控制，旨在为数字取证领域提供高效、智能、可扩展的解决方案。

### 核心能力

- 🎯 **智能任务规划**：基于 LLM 的自动化取证任务规划系统
- 🔍 **视觉理解**：集成 VisionTasker 实现精准的 UI 元素识别和操作
- 🤖 **智能调度器选择**：基于 BGE 语义匹配，自动路由到复用模式或探索模式
- 📱 **跨应用支持**：支持微信、WhatsApp、Telegram、支付宝等主流应用
- 🧠 **RAG 模板匹配**：历史经验复用 + 新任务自动探索，模板库持续成长
- 📊 **端到端执行**：从案件分析到取证执行的全自动化流程

---

## 🌟 核心特性

### 1. 智能任务规划系统

- **自动化任务生成**：基于应用特性和取证目标自动生成执行计划
- **多级任务分解**：将复杂取证任务分解为可执行的原子操作
- **智能策略选择**：根据应用类型和任务特点选择最优执行策略

### 2. 视觉理解与操作

- **精准元素识别**：基于 YOLO + CLIP 的混合 UI 元素检测
- **语义理解**：结合 OCR 和语义分析实现自然语言指令理解
- **自适应操作**：根据界面布局动态调整操作策略

### 3. 智能调度器选择

- **调度器选择器**：基于 BGE 语义匹配自动路由，相似度 ≥ 阈值用老调度器（复用），< 阈值用新调度器（探索）
- **老调度器（复用模式）**：XML 文本匹配 + VisionTasker 视觉 fallback，高效复用历史经验
- **新调度器（探索模式）**：纯 LLM 驱动，简化 UI 树 + 坐标执行，适应新任务并积累新模板

### 4. 智能匹配优化

- **语义匹配器**：基于 BGE 模型的语义相似度匹配
- **RAG 模板匹配**：利用检索增强生成优化动作选择
- **脚本注册系统**：支持专用取证脚本的自动调用

### 5. 完善的数据管理

- **结构化存储**：按案例、任务、步骤的多层级数据组织
- **实时数据固化**：执行过程中的数据实时落盘
- **可视化分析**：提供丰富的数据可视化和分析工具

---

## 🏗️ 架构概览

### 系统架构图

```
用户输入 (case + goals)
       ↓
┌──────────────────────────────────────────────────┐
│  规划层 (auto_forensic_planning.py)               │
│  ├─ ADB 获取设备包名 → Google Play 爬取应用名称   │
│  ├─ 生成 package_name_mapping.txt                 │
│  └─ LLM 生成 forensic_plan.json                  │
└──────────────────────────────────────────────────┘
       ↓ forensic_plan.json
┌──────────────────────────────────────────────────┐
│  执行层 (run_forensic_plan.py)                    │
│  └─ 调度器选择器 (BGE 语义匹配)                   │
│     ├─ 相似度 ≥ 0.75 → 老调度器（复用模式）       │
│     └─ 相似度 < 0.75 → 新调度器（探索模式）       │
└──────────────────────────────────────────────────┘
       ↓                    ↓
┌────────────────┐  ┌────────────────┐
│  老调度器       │  │  新调度器       │
│  scheduler_vt  │  │  scheduler_llm │
│  XML匹配优先   │  │  简化 UI 树    │
│  VT fallback   │  │  LLM 坐标执行  │
│                │  │  自动保存模板   │
└────────────────┘  └────────────────┘
```

### 技术栈

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 语言模型 | Qwen 3.5-27B | 任务规划、决策、步骤生成 |
| 语义匹配 | BGE-large-zh-v1.5 | 调度器选择、RAG 模板检索 |
| 视觉模型 | VisionTasker (YOLO + CLIP) | UI 元素检测和分类（老调度器 fallback） |
| 设备控制 | ADB + uiautomator2 | Android 自动化 |
| 应用信息 | Google Play Scraper | 包名→应用名称映射 |
| 数据存储 | JSON | 结构化数据存储 |

---

## 📁 目录结构

```
MobiAgent/
├── run_end_to_end.py                # 端到端入口（规划→执行）
├── auto_forensic_planning.py        # 规划层入口（单独使用）
├── run_forensic_plan.py             # 执行层入口（单独使用）
├── test_old_scheduler.py            # 老调度器单独测试
├── test_scheduler_llm.py            # 新调度器单独测试
├── test_auto_planning.py            # 规划层单独测试
│
├── runner/forensiflow/              # 核心代码
│   ├── core/
│   │   ├── scheduler_vt.py          # 老调度器（复用模式）
│   │   ├── scheduler_llm.py         # 新调度器（探索模式）
│   │   ├── scheduler_selector.py    # 调度器选择器（智能路由）
│   │   ├── forensic_planner.py      # 取证规划器
│   │   ├── rag_template_matcher.py  # RAG 模板匹配（BGE）
│   │   ├── xml_utils.py             # XML 简化工具
│   │   └── config.py                # 统一配置管理
│   ├── devices/
│   │   ├── android.py               # Android 设备管理
│   │   ├── app_info_fetcher.py      # Google Play 应用信息爬取
│   │   └── extract_and_query_apps.py # 设备应用提取工具
│   └── scripts/                     # 专用取证脚本
│
├── external/
│   ├── VisionTasker/                # VisionTasker 视觉模型
│   ├── models/                      # BGE 语义模型
│   │   └── bge-large-zh-v1.5/
│   └── rag_templates/               # RAG 模板库
│       └── all_templates.json
│
├── docs/                            # 文档目录
├── data/                            # 运行时数据（gitignored）
├── .env.template                    # 环境配置模板
└── requirements.txt                 # Python 依赖
```

---

## 🚀 快速开始

### 环境要求

- Python 3.8+
- Android 设备或模拟器
- ADB (Android Debug Bridge)
- 至少 8GB RAM

### 安装步骤

#### 1. 克隆项目

```bash
git clone <repository-url>
cd MobiAgent
```

#### 2. 安装依赖

```bash
pip install -r requirements.txt
```

#### 3. 配置环境变量

```bash
cp .env.template .env
```

编辑 `.env` 文件，配置必要的 API 密钥：

```bash
# Qwen API（必需）
QWEN_API_KEY=your-qwen-api-key

# ChatGLM API（可选）
CHATGLM_API_KEY=your-chatglm-api-key
```

#### 4. 连接 Android 设备

```bash
adb devices
```

#### 5. 准备模型文件

- **BGE 模型**：下载 `bge-large-zh-v1.5` 到 `external/models/bge-large-zh-v1.5/`
- **VisionTasker 模型**（老调度器需要）：下载到 `external/VisionTasker/pt_model/`

### 基础使用

#### 方式 1：端到端执行（推荐）

```bash
# 自动完成：提取应用 → 生成规划 → 执行取证
python run_end_to_end.py --case "涉嫌诈骗案" --goals "提取 WhatsApp 聊天记录"

# 从文件读取
python run_end_to_end.py --case-file case.txt --goals-file goals.txt

# 使用已有规划文件
python run_end_to_end.py --plan data/forensic_plans/forensic_plan_xxx.json
```

#### 方式 2：分步执行

```bash
# 步骤1：生成取证规划
python auto_forensic_planning.py --case "案件描述" --goals "取证目标"

# 步骤2：执行规划
python run_forensic_plan.py --plan data/forensic_plans/forensic_plan_xxx.json
```

#### 方式 3：单独测试调度器

```bash
# 测试老调度器
python test_old_scheduler.py --app "WhatsApp Messenger" --task "消息/会话总列表界面全量提取"

# 测试新调度器
python test_scheduler_llm.py --package "com.whatsapp" --app "WhatsApp Messenger" --task "提取联系人信息"
```

---

## 💡 核心模块说明

### 1. 调度器选择器 (SchedulerSelector)

基于 BGE 语义匹配自动路由到最优调度器：

```python
from runner.forensiflow.core.scheduler_selector import SchedulerSelector
from runner.forensiflow.core.rag_template_matcher import RAGTemplateMatcher

rag_matcher = RAGTemplateMatcher()
selector = SchedulerSelector(rag_matcher=rag_matcher, threshold=0.75)

result = selector.select_scheduler(
    app_name="WhatsApp Messenger",
    task_description="消息/会话总列表界面全量提取"
)
# result.scheduler_type == "old" → 老调度器（有历史模板）
# result.scheduler_type == "new" → 新调度器（新任务探索）
```

### 2. 老调度器 (TaskSchedulerVT) - 复用模式

适合有历史经验的高相似度任务，XML 文本匹配优先，VisionTasker 视觉匹配作为 fallback：

```python
from runner.forensiflow.core.scheduler_vt import TaskSchedulerVT

scheduler = TaskSchedulerVT(
    device=device,
    planner_api_key="your-api-key",
    planner_model="qwen3.5-27b"
)

result = scheduler.run_task(
    app="WhatsApp Messenger",
    old_task="消息/会话总列表界面全量提取",
    task="消息/会话总列表界面全量提取",
    max_steps=20,
    use_abstract_task=True
)
```

### 3. 新调度器 (SimpleLLMScheduler) - 探索模式

纯 LLM 驱动，适应新任务，完成后自动保存模板到 RAG 库：

```python
from runner.forensiflow.core.scheduler_llm import SimpleLLMScheduler

scheduler = SimpleLLMScheduler(
    device=device,
    api_key="your-api-key",
    model="qwen3.5-27b"
)

result = scheduler.run_forensic_task(
    package_name="com.whatsapp",
    app_name="WhatsApp Messenger",
    task_description="提取联系人信息",
    constraint="仅针对与 kndxx 相关的联系人",
    max_steps=20
)
```

### 4. 取证规划器 (ForensicPlanner)

基于 LLM 从案件背景和取证目标生成结构化规划：

```python
from runner.forensiflow.core.forensic_planner import ForensicPlanner

planner = ForensicPlanner(api_key="your-api-key", model="qwen3.5-27b")
plan = planner.create_forensic_plan(
    case_background="涉嫌网络诈骗案...",
    forensic_goals="提取 WhatsApp 聊天记录\n提取微信联系人"
)
```

### 5. RAG 模板匹配器 (RAGTemplateMatcher)

使用 BGE-large-zh-v1.5 进行语义检索，匹配历史任务模板：

```python
from runner.forensiflow.core.rag_template_matcher import RAGTemplateMatcher

matcher = RAGTemplateMatcher()
results = matcher.search(app="WhatsApp Messenger", task="提取联系人", top_k=3)
```

### 6. 设备管理 (AndroidDevice)

```python
from runner.forensiflow.devices.android import AndroidDevice

device = AndroidDevice(adb_endpoint="device_serial")
device.app_start(package_name="com.whatsapp")
device.click(x, y)
device.input_text(text="Hello")
device.swipe(start_x, start_y, end_x, end_y)
screenshot = device.screenshot()
xml_dump = device.get_xml()
```

---

## 📋 使用指南

### 任务配置格式

#### 基础任务列表

```json
[
    "提取WhatsApp所有联系人列表信息",
    "提取WhatsApp中所有联系人聊天记录信息",
    "提取WhatsApp通话记录"
]
```

#### 结构化任务

```json
[
    {
        "task_description": "提取微信联系人",
        "app_name": "微信",
        "task_type": "社交",
        "constraint": "只获取最近30天的联系人"
    }
]
```

#### 取证规划任务

```json
{
    "case_analysis_summary": "案件描述",
    "forensic_plan": [
        {
            "app_name": "WhatsApp",
            "package_name": "com.whatsapp",
            "tasks": [
                {
                    "task_level": 1,
                    "task_type": "信息提取",
                    "task_description": "提取联系人列表",
                    "target_objects": ["联系人"],
                    "constraint": ""
                }
            ]
        }
    ]
}
```

### 执行流程说明

#### 1. 抽象任务执行流程

```
用户任务
    ↓
任务理解（LLM）
    ↓
步骤规划（LLM + VisionTasker）
    ↓
循环执行每个步骤
    ├→ 屏幕截图
    ├→ UI 元素检测（YOLO）
    ├→ 元素分类（CLIP）
    ├→ 动作匹配（Semantic/RAG）
    ├→ 执行动作（uiautomator2）
    └→ 结果验证
    ↓
任务完成
```

#### 2. 取证规划执行流程

```
案件描述
    ↓
应用分析（LLM）
    ↓
任务分解（LLM）
    ↓
执行规划（按应用、按级别）
    ↓
逐任务执行
    ├→ 应用启动
    ├→ 任务执行
    ├→ 数据采集
    └→ 结果保存
    ↓
生成报告
```

### 调试模式

#### 启用详细日志

```bash
# 在代码中设置
import logging
logging.basicConfig(level=logging.DEBUG)
```

#### 单步调试模式

```python
result = scheduler.run_task(
    task="测试任务",
    max_steps=1,  # 只执行一步
    debug=True    # 启用调试模式
)
```

---

## ⚙️ 配置说明

### 环境变量配置

#### 必需配置

```bash
# Qwen API（必需）
QWEN_API_KEY=your-qwen-api-key
```

#### 可选配置

```bash
# ChatGLM API
CHATGLM_API_KEY=your-chatglm-api-key

# OCR API
OCR_API_KEY=your-ocr-api-key

# 性能参数
SEMANTIC_MATCH_THRESHOLD=0.7
MAX_RETRIES=3
TIMEOUT=30
```

### 模型配置

所有组件统一使用 `qwen3.5-27b` 模型：

```python
# 自动应用，无需手动配置
model = "qwen3.5-27b"
```

### 设备配置

#### USB 连接

```bash
adb devices
# 输出示例：
# LIst of devices attached
# emulator-5554   device
```

#### 网络连接

```bash
adb connect 192.168.1.100:5555
```

### VisionTasker 配置

确保模型文件在正确位置：

```bash
~/models/VisionTasker/pt_model/
├── yolo_mdl.pt              # YOLO 检测模型
├── yolo_vins_14_mdl.pt      # YOLO VINS 模型
├── clip_mdl.pth             # CLIP 分类模型
└── clip_labels/             # 分类标签目录
    ├── android_labels.txt
    └── ...
```

---

## 📊 数据管理

### 数据目录结构

```
data/
├── [案例ID]/
│   ├── screenshots/         # 原始截图
│   ├── xml_dumps/          # UI 结构
│   ├── highlighted/        # 高亮显示
│   ├── workflows/          # 执行记录
│   └── results/            # 执行结果
├── run_*/
│   ├── clip/               # CLIP 处理结果
│   ├── ocr/                # OCR 识别结果
│   ├── layout/             # 布局分析
│   └── uied/               # UI 元素检测
├── forensic_plans/         # 取证规划
└── app_info_cache/         # 应用信息缓存
```

### 数据格式

#### 执行结果 JSON

```json
{
    "completed": true,
    "total_steps": 15,
    "actions": [
        {
            "step": 1,
            "action": "click",
            "element": "登录按钮",
            "timestamp": "2024-01-01 12:00:00"
        }
    ],
    "data_dir": "data/case_001",
    "screenshots": ["1.jpg", "2.jpg"],
    "error": ""
}
```

---

## 🔧 高级功能

### 1. 自定义取证脚本

创建自定义脚本并注册：

```python
# runner/forensiflow/scripts/custom_script.py

def extract_data(device):
    """自定义取证函数"""
    # 实现取证逻辑
    data = device.get_ui_data()
    # 保存数据
    return True  # 必须返回 True
```

在 `script_registry.py` 中注册：

```python
register_script("custom_extract", extract_data)
```

### 2. 批量任务执行

使用 `run_all_tasks.py` 执行多个任务：

```bash
python run_all_tasks.py \
    --task-file runner/forensiflow/task.json \
    --max-steps 35 \
    --model qwen3.5-27b
```

### 3. 约束条件执行

在任务中添加约束条件：

```python
result = scheduler.run_task(
    task="提取联系人",
    constraint="只获取最近30天的数据",
    max_steps=20
)
```

### 4. 应用分类执行

基于应用分类自动选择执行策略：

```python
# 社交应用
if app_category == "social":
    strategy = "deep_analysis"

# 电商应用
elif app_category == "ecommerce":
    strategy = "transaction_focus"

# 金融应用
elif app_category == "finance":
    strategy = "security_priority"
```

---

## ❓ 常见问题

### Q1: 设备连接失败

**问题**：`adb devices` 看不到设备

**解决方案**：
1. 检查 USB 调试是否开启
2. 尝试重启 ADB：`adb kill-server && adb start-server`
3. 检查驱动是否正确安装
4. 尝试网络连接：`adb connect <ip>:5555`

### Q2: 模型加载失败

**问题**：找不到 VisionTasker 模型文件

**解决方案**：
1. 确认模型文件路径：`~/models/VisionTasker/pt_model/`
2. 检查文件完整性
3. 确认文件权限：`chmod +r ~/models/VisionTasker/pt_model/*`

### Q3: API 调用失败

**问题**：Qwen API 返回错误

**解决方案**：
1. 检查 API Key 是否正确
2. 确认账户余额
3. 检查网络连接
4. 查看 API 状态页面

### Q4: 任务执行不完整

**问题**：任务提前结束

**解决方案**：
1. 增加 `max_steps` 参数
2. 检查是否有错误日志
3. 启用调试模式查看详细日志
4. 检查设备是否有弹窗或权限请求

### Q5: 脚本执行误判失败

**问题**：脚本成功执行但被标记为失败

**解决方案**：
确保脚本函数返回 `True`：

```python
def extract_data(device):
    # 执行逻辑
    return True  # 必须返回 True
```

---

## 🛠️ 开发指南

### 代码规范

- 遵循 PEP 8 编码规范
- 使用类型提示
- 编写文档字符串
- 保持模块职责单一

### 测试

```bash
# 单元测试
pytest tests/

# 集成测试
python test_old_scheduler.py --task "测试任务"

# 端到端测试
python run_all_tasks.py --task-file test_tasks.json
```

### 贡献流程

1. Fork 项目
2. 创建特性分支
3. 提交更改
4. 推送到分支
5. 创建 Pull Request

### 文档更新

更新相关文档：
- 功能说明
- API 文档
- 使用示例
- 变更日志

---

## 📈 性能优化

### 加速策略

1. **启用缓存**：应用信息和UI结构缓存
2. **并行处理**：多任务并行执行
3. **模型优化**：使用量化模型
4. **网络优化**：API 调用批处理

### 内存管理

- 及时清理临时文件
- 使用生成器处理大数据
- 定期清理缓存

---

## 🔒 安全注意事项

1. **API 密钥保护**：不要提交到版本控制
2. **数据隐私**：妥善处理取证数据
3. **权限管理**：最小权限原则
4. **日志脱敏**：避免记录敏感信息

---

## 📚 相关文档

- [取证规划器使用指南](docs/FORENSIC_PLANNER_GUIDE.md)
- [执行流程说明](docs/EXECUTION_FLOW.md)
- [API 设置指南](docs/API_SETUP_GUIDE.md)
- [RAG 集成文档](docs/RAG_INTEGRATION.md)
- [记忆机制说明](docs/MEMORY_MECHANISM.md)

---

## 📝 更新日志

### v2.0.0 (2026-04)
- 🎉 智能调度器选择器：基于 BGE 语义匹配自动路由新老调度器
- ✨ RAG 模板匹配：历史经验复用 + 新任务自动探索
- ✨ 端到端执行：从案件分析到取证执行的全自动化流程
- ✨ 应用信息持久缓存：成功/失败查询均缓存，避免重复请求
- ✨ XML 简化匹配：老调度器使用简化 XML，精确匹配优先

### v1.0.0 (2026-03)
- 🎉 首个稳定版本
- ✨ 老调度器（VisionTasker + XML 匹配）
- ✨ 新调度器（纯 LLM 驱动）
- ✨ 取证规划层（LLM 任务规划）
- ✨ 多应用支持

---

## 🤝 贡献

欢迎贡献代码、报告问题或提出建议！

---

## 📄 许可证

MIT License - 详见 LICENSE 文件

---

## 🙏 致谢

- VisionTasker 团队
- Qwen 团队
- 所有贡献者

---

## 🚀 项目发展路线

### 🟢 第一阶段：基础智能体架构与视觉决策（已完成）

- 基于 LLM 的任务拆分与动作决策
- VisionTasker 视觉模块对 Android UI 的识别与理解
- 自动生成操作步骤并驱动设备执行

### 🟢 第二阶段：混合解析引擎与效率优化（已完成）

- "XML 优先，视觉兜底"混合识别策略
- UI Automator 底层 XML 节点解析
- 轻量级节点匹配算法，显著降低 LLM 调用频率

### 🟢 第三阶段：智能任务规划与调度（已完成）

- 取证规划层：LLM 自动生成结构化取证任务规划
- 调度器选择器：BGE 语义匹配智能路由新老调度器
- RAG 模板匹配：历史经验复用 + 新任务自动探索
- 端到端执行：从案件分析到取证执行的全自动化

### 🔵 第四阶段：专业取证业务模块（已完成）

- 微信、WhatsApp、Telegram 等应用的专业化取证模块
- 差异化证据提取算法
- 可视化操作界面与实时监控

### 🟡 第五阶段：脚本自动生成与自进化闭环（规划中）

构建新调度器的脚本自动生成能力，形成"探索→生成→复用"的自进化闭环：

- 新调度器导航到目标界面后，自动分析 UI 树结构并生成提取脚本
- 生成的脚本保存到脚本库，统一注册到 ScriptRegistry
- 老调度器复用时通过 CallScript 直接调用已生成的脚本
- 实现导航模板 + 提取脚本的关联绑定，越用越快

```
探索（新调度器）              复用（老调度器）
LLM 导航到目标界面            模板导航到目标界面
      ↓                            ↓
分析 UI 树 → 自动生成脚本    CallScript 调用已有脚本
      ↓                            ↓
 保存到脚本库               高效结构化提取
```

### 🔴 第六阶段：司法合规与防篡改加固（规划中）

- 完整日志记录与哈希校验机制
- 防篡改与完整性验证
- 证据合法、原始、可追溯、可验证

---

<div align="center">

**[⬆ 返回顶部](#mobiagent---智能移动端取证自动化框架)**

Made with ❤️ by ForensiFlow Team

</div>
