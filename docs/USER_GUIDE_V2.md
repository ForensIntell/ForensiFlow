# ForensiFlow V2 系统使用指南

## 📋 系统架构概述

```
┌─────────────────────────────────────────────────────────┐
│                   取证规划层                              │
│         (ForensicPlanner + 调度器选择逻辑)                 │
└─────────────────────────────────────────────────────────┘
                           │
                    使用 BGE 进行语义匹配
                           │
                 ┌─────────┴─────────┐
                 │                   │
         相似度 < 阈值         相似度 >= 阶值
         (默认 < 0.75)        (默认 >= 0.75)
                 │                   │
         ┌───────┴───────┐   ┌──────┴───────┐
         │   新任务       │   │   重复任务    │
         │  新调度器      │   │  老调度器     │
         │ (探索模式)     │   │  (复用模式)   │
         └───────┬───────┘   └──────┬───────┘
                 │                   │
         生成成功案例          使用 RAG 库
         (经验积累)           (快速执行)
                 │                   │
         └───────┴───────────────────┘
                   │
            存入 RAG 模板库
            (供后续匹配使用)
```

---

## 🚀 快速开始

### 前置准备

#### 1. 环境配置

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 API 密钥
cp .env.template .env
# 编辑 .env 文件，填入你的 QWEN_API_KEY
```

#### 2. 连接 Android 设备

```bash
# 启动 ADB 服务
adb start-server

# 检查设备连接
adb devices

# 确保设备已连接并授权
```

#### 3. 准备 RAG 模板库（可选，但推荐）

首次运行时 RAG 库可能是空的，系统会自动积累经验。如果想快速体验老调度器功能：

```bash
# 确保 external/rag_templates/ 目录存在
mkdir -p external/rag_templates

# 可以放入已有的模板文件（如果有）
# 例如：whatsapp_templates.json
```

---

## 📖 完整使用流程

### 步骤 1：生成取证规划

#### 方式 A：使用规划层自动生成（推荐）

```bash
# 运行自动取证规划
python auto_forensic_planning.py
```

**输入：**
- 案件描述（例如："提取 WhatsApp 的联系人信息和聊天记录"）
- 设备已安装应用列表

**输出：**
- JSON 格式的取证任务规划文件
- 位置：`data/forensic_plans/forensic_plan_YYYYMMDD_HHMMSS.json`

**示例输出：**
```json
{
  "case_analysis_summary": "案件需要提取WhatsApp的联系人信息和聊天记录...",
  "forensic_plan": [
    {
      "app_name": "WhatsApp Messenger",
      "package_name": "com.whatsapp",
      "tasks": [
        {
          "task_level": 1,
          "task_type": "full_extraction",
          "task_description": "全局联系人列表界面遍历抓取",
          "target_objects": ["联系人"],
          "constraint": ""
        },
        {
          "task_level": 1,
          "task_type": "full_extraction",
          "task_description": "消息/会话总列表界面全量提取",
          "target_objects": ["会话列表"],
          "constraint": ""
        }
      ]
    }
  ]
}
```

#### 方式 B：手动创建规划文件

如果不想使用规划层，可以手动创建 JSON 文件：

```bash
# 创建规划文件
cat > data/forensic_plans/my_plan.json << 'EOF'
{
  "case_analysis_summary": "我的案件描述",
  "forensic_plan": [
    {
      "app_name": "WhatsApp Messenger",
      "package_name": "com.whatsapp",
      "tasks": [
        {
          "task_level": 1,
          "task_type": "full_extraction",
          "task_description": "提取WhatsApp联系人列表",
          "target_objects": [],
          "constraint": ""
        }
      ]
    }
  ]
}
EOF
```

---

### 步骤 2：执行取证任务（使用智能调度器）

#### 完整执行规划文件中的所有任务

```bash
# 执行规划文件中的所有任务
python run_forensic_plan.py --plan data/forensic_plans/forensic_plan_20260410_123456.json
```

**系统会自动：**
1. 加载规划文件
2. 对每个任务使用调度器选择器进行 BGE 语义匹配
3. 根据相似度智能选择调度器：
   - **相似度 >= 0.75** → 使用老调度器（快速复用历史经验）
   - **相似度 < 0.75** → 使用新调度器（探索并生成新模板）
4. 执行任务并保存结果

#### 执行特定应用的任务

```bash
# 只执行 WhatsApp 相关的任务
python run_forensic_plan.py \
  --plan data/forensic_plans/forensic_plan_20260410_123456.json \
  --app "WhatsApp Messenger"
```

#### 执行特定索引的任务

```bash
# 只执行第一个任务（索引为 0）
python run_forensic_plan.py \
  --plan data/forensic_plans/forensic_plan_20260410_123456.json \
  --task-index 0
```

#### 指定设备（多设备时）

```bash
# 使用特定设备
python run_forensic_plan.py \
  --plan data/forensic_plans/forensic_plan_20260410_123456.json \
  --device-serial emulator-5554
```

---

### 步骤 3：查看执行结果

#### 执行日志（控制台输出）

```
================================================================================
📋 取证任务规划
================================================================================
案件分析: 本案需要提取WhatsApp的联系人信息和聊天记录...
应用数量: 1
================================================================================

================================================================================
📱 应用: WhatsApp Messenger (com.whatsapp)
📋 任务数: 2
================================================================================

────────────────────────────────────────────────────────────────────────────
📝 任务 #0: [Level 1] 全局联系人列表界面遍历抓取
────────────────────────────────────────────────────────────────────────────

🔍 调度器选择分析...
📊 选择结果: 相似度 0.852 >= 阈值 0.750，使用老调度器复用历史经验
   相似度分数: 0.852
   使用调度器: 老调度器（复用模式）

🔄 使用老调度器执行任务（复用历史经验）
...
✅ 任务 #0 完成
```

#### 执行结果汇总文件

**位置：** `data/forensic_plans/forensic_plan_YYYYMMDD_HHMMSS_execution_summary.json`

**内容示例：**
```json
{
  "plan_file": "data/forensic_plans/forensic_plan_20260410_123456.json",
  "case_analysis": "案件分析...",
  "apps_executed": [
    {
      "app_name": "WhatsApp Messenger",
      "package_name": "com.whatsapp",
      "tasks_executed": [
        {
          "task_index": 0,
          "task_level": 1,
          "task_type": "full_extraction",
          "task_description": "全局联系人列表界面遍历抓取",
          "completed": true,
          "total_steps": 5,
          "data_dir": "data/run_llm_20260410_123456",
          "scheduler_used": "old",  // 使用的调度器
          "similarity_score": 0.852  // 相似度分数
        }
      ],
      "tasks_completed": [0],
      "tasks_failed": []
    }
  ],
  "total_tasks": 2,
  "completed_tasks": 2,
  "failed_tasks": 0
}
```

#### 执行数据目录

**位置：** `data/run_llm_YYYYMMDD_HHMMSS/` 或 `data/run_YYYYMMDD_HHMMSS/`

**包含内容：**
- 截图：`screenshots/`
- XML dump：`window_dump_*.xml`
- 执行日志：`execution.log`
- 提取的数据：取决于具体任务

---

## 🎯 核心特性说明

### 1. 智能调度器选择

系统会自动根据任务相似度选择最合适的调度器：

**高相似度任务（>= 0.75）：**
```
任务: "提取WhatsApp联系人列表"
  ↓ BGE 匹配
相似度: 0.85（与 RAG 库中的模板高度相似）
  ↓ 调度器选择
使用: 老调度器（复用模式）
优点:
  - 执行速度快（使用历史经验）
  - API 调用成本低
  - 成功率高（经验丰富）
```

**低相似度任务（< 0.75）：**
```
任务: "分析WhatsApp聊天记录的情感倾向"
  ↓ BGE 匹配
相似度: 0.62（没有足够相似的模板）
  ↓ 调度器选择
使用: 新调度器（探索模式）
优点:
  - 探索新任务
  - 生成成功案例模板
  - 自动保存到 RAG 库
  - 下次执行时会更快
```

### 2. 经验自动积累

**新调度器生成的模板会自动保存：**

位置：`external/rag_templates/`

文件命名：`{app_name}_templates.json`

**示例：**
```json
[
  {
    "app": "WhatsApp Messenger",
    "task": "全局联系人列表界面遍历抓取",
    "created_at": "2026-04-10T18:30:00",
    "scheduler_type": "new",
    "steps": [
      {"action": "Click", "target": "聊天按钮"},
      {"action": "Click", "target": "联系人"},
      {"action": "CallScript", "target": "提取联系人列表"}
    ]
  }
]
```

**下次执行类似任务时：**
- BGE 会匹配到这个新模板
- 相似度会很高（因为任务相同或相似）
- 自动切换到老调度器快速执行

### 3. 阈值配置

可以通过环境变量调整阈值：

```bash
# 编辑 .env 文件
SCHEDULER_SELECTION_THRESHOLD=0.75  # 默认值

# 或者在运行时设置
export SCHEDULER_SELECTION_THRESHOLD=0.80
python run_forensic_plan.py --plan ...
```

**阈值调优建议：**

| 阈值设置 | 效果 | 适用场景 |
|---------|------|---------|
| 0.85（较高） | 更严格，只有非常相似的任务才用老调度器 | 初期积累阶段，确保模板质量 |
| 0.75（推荐） | 平衡探索和利用 | 日常使用，推荐设置 |
| 0.65（较低） | 更宽松，更多任务会使用老调度器 | 后期优化阶段，提升速度 |

---

## 📊 监控系统表现

### 查看调度器使用分布

从执行汇总文件中统计：

```python
import json

with open('data/forensic_plans/forensic_plan_XXX_execution_summary.json') as f:
    summary = json.load(f)

new_scheduler_tasks = 0
old_scheduler_tasks = 0

for app in summary['apps_executed']:
    for task in app['tasks_executed']:
        if task.get('scheduler_used') == 'new':
            new_scheduler_tasks += 1
        else:
            old_scheduler_tasks += 1

print(f"新调度器任务: {new_scheduler_tasks}")
print(f"老调度器任务: {old_scheduler_tasks}")
print(f"复用率: {old_scheduler_tasks / (new_scheduler_tasks + old_scheduler_tasks) * 100:.1f}%")
```

### 查看相似度分布

```python
import json

with open('data/forensic_plans/forensic_plan_XXX_execution_summary.json') as f:
    summary = json.load(f)

scores = []
for app in summary['apps_executed']:
    for task in app['tasks_executed']:
        score = task.get('similarity_score', 0)
        scores.append(score)

print(f"平均相似度: {sum(scores)/len(scores):.3f}")
print(f"最高相似度: {max(scores):.3f}")
print(f"最低相似度: {min(scores):.3f}")
```

---

## 🔧 常见使用场景

### 场景 1：首次执行新任务

```bash
# 1. 生成规划
python auto_forensic_planning.py

# 2. 执行任务（所有任务都是新的，都会用新调度器）
python run_forensic_plan.py --plan data/forensic_plans/forensic_plan_XXX.json

# 3. 结果：新调度器探索并生成模板
```

### 场景 2：重复执行相同任务

```bash
# 1. 使用相同的规划文件
python run_forensic_plan.py --plan data/forensic_plans/forensic_plan_XXX.json

# 2. 结果：大部分任务会用老调度器（因为 RAG 库中已有模板）
# 3. 执行速度会明显提升
```

### 场景 3：添加新的取证应用

```bash
# 1. 确保应用信息已爬取
python app_info_fetcher.py  # 会自动从 Google Play 爬取

# 2. 生成新应用的规划
python auto_forensic_planning.py

# 3. 执行任务（新应用的任务会优先用新调度器）
python run_forensic_plan.py --plan data/forensic_plans/forensic_plan_XXX.json
```

### 场景 4：调试单个任务

```bash
# 只执行特定任务
python run_forensic_plan.py \
  --plan data/forensic_plans/forensic_plan_XXX.json \
  --app "WhatsApp Messenger" \
  --task-index 0
```

---

## ⚠️ 注意事项

### 1. API 密钥配置

确保 `.env` 文件中配置了有效的 API 密钥：

```bash
QWEN_API_KEY=your-key-here
```

### 2. 设备连接

- 确保 ADB 已连接
- 设备已解锁
- 已授权 USB 调试

### 3. 网络连接

- BGE 模型需要加载（首次运行会下载）
- LLM API 需要网络连接

### 4. 首次运行

- RAG 库可能为空，所有任务都会用新调度器
- 这是正常的，系统会自动积累经验
- 第二次运行相同任务时会明显更快

### 5. 模板质量

- 新调度器生成的模板会自动保存
- 建议定期检查 `external/rag_templates/` 中的模板质量
- 可以手动删除低质量模板

---

## 📈 性能优化建议

### 1. 提升复用率

- **设置合理的阈值**：从 0.75 开始，根据实际情况调整
- **积累基础模板**：前期多执行常见任务，建立模板库
- **统一任务描述**：使用相似的任务描述语言

### 2. 提升成功率

- **定期检查模板**：删除低质量或错误的模板
- **调整阈值**：如果失败率高，适当提高阈值
- **人工审核**：初期人工审核新任务生成的模板

### 3. 降低成本

- **提高复用率**：重复任务使用老调度器，API 调用更少
- **批量执行**：一次性执行多个任务，减少重复初始化开销
- **使用更快的模型**：在 `config.py` 中调整模型配置

---

## 🎓 总结

### 系统优势

1. **自动化程度高**：从规划到执行全自动化
2. **智能调度**：自动选择最合适的调度器
3. **经验积累**：越用越智能，重复任务越来越快
4. **易于扩展**：支持添加新的取证应用和任务

### 典型工作流程

```
第 1 次执行：新调度器探索 → 生成模板 → 存入 RAG 库
第 2 次执行：BGE 匹配 → 老调度器复用 → 快速完成
第 3 次执行：BGE 匹配 → 老调度器复用 → 快速完成
...
系统越来越快！
```

### 下一步

- 尝试执行你的第一个取证任务
- 观察调度器选择结果
- 查看生成的模板
- 调整阈值以优化性能

---

**文档版本**: v2.0
**最后更新**: 2026-04-10
**维护者**: ForensiFlow Team
