# 🎯 MobiAgent 端到端执行指南

## 核心逻辑：规划层为入口

```
用户输入：case + goals
      ↓
规划层（auto_forensic_planning.py）
  ├─ 输入：case + goals
  ├─ 输出：forensic_plan_XXX.json
      ↓
执行层（run_forensic_plan.py）
  ├─ 输入：forensic_plan_XXX.json
  └─ 输出：执行结果
```

---

## 🚀 快速开始

### 方式 1：命令行指定（推荐）

```bash
python run_end_to_end.py \
  --case "涉嫌网络诈骗案，需要提取嫌疑人的通讯记录" \
  --goals "提取 WhatsApp 联系人列表\\n提取微信聊天记录"
```

### 方式 2：从文件读取

```bash
# case.txt
涉嫌网络诈骗案...

# goals.txt
提取 WhatsApp 联系人列表
提取微信聊天记录

# 执行
python run_end_to_end.py --case-file case.txt --goals-file goals.txt
```

### 方式 3：交互式输入

```bash
python run_end_to_end.py
# 会提示你输入 case 和 goals
```

---

## 📖 完整示例

### 示例 1：网络诈骗案取证

```bash
python run_end_to_end.py \
  --case "2024年3月，张三报案称在网络平台被诈骗，损失50万元。嫌疑人通过 WhatsApp 和微信进行联系。" \
  --goals "提取 WhatsApp 联系人列表\\n提取微信聊天记录\\n提取支付宝交易明细"
```

### 示例 2：只执行特定应用

```bash
python run_end_to_end.py \
  --case "..." \
  --goals "..." \
  --app "WhatsApp Messenger"
```

### 示例 3：只执行特定任务

```bash
python run_end_to_end.py \
  --case "..." \
  --goals "..." \
  --task-index 0
```

### 示例 4：使用已有规划文件

```bash
python run_end_to_end.py \
  --plan data/forensic_plans/forensic_plan_20260410_123456.json
```

---

## 📝 参数说明

| 参数 | 必需/可选 | 说明 | 示例 |
|------|----------|------|------|
| `--case` | 可选 | 案件背景 | `"涉嫌诈骗案..."` |
| `--case-file` | 可选 | 从文件读取案件背景 | `case.txt` |
| `--goals` | 可选 | 取证目标（`\\n`换行） | `"提取联系人\\n提取聊天记录"` |
| `--goals-file` | 可选 | 从文件读取取证目标 | `goals.txt` |
| `--app` | 可选 | 只执行特定应用 | `"WhatsApp Messenger"` |
| `--task-index` | 可选 | 只执行特定任务 | `0` |
| `--plan` | 可选 | 使用已有规划文件（跳过规划） | `plan.json` |
| `--device-serial` | 可选 | 设备序列号 | `emulator-5554` |
| `--model` | 可选 | LLM 模型 | `qwen3.5-27b` |
| `--threshold` | 可选 | 调度器选择阈值 | `0.75` |

**注意：** 如果既没有 `--case/--case-file` 也没有 `--plan`，则进入交互模式。

---

## 🔧 工作流程对比

### 手动执行（两步）

```bash
# 步骤1：规划层
python auto_forensic_planning.py --case "..." --goals "..."
# 输出：data/forensic_plans/forensic_plan_XXX.json

# 步骤2：执行层
python run_forensic_plan.py --plan data/forensic_plans/forensic_plan_XXX.json
```

### 端到端执行（一步）

```bash
python run_end_to_end.py --case "..." --goals "..."
# 自动完成：规划层 → 执行层
```

**效果完全一样！**

---

## ⚠️ 重要说明

### 规划层是入口

- 规划层需要：`case` + `goals`
- 规划层输出：`forensic_plan_XXX.json`
- 执行层需要：`forensic_plan_XXX.json`

### 端到端脚本的作用

**不是替代规划层**，而是**串联**规划层和执行层：
- 调用规划层生成规划文件
- 自动传递给执行层
- 用户不需要手动复制文件路径

---

## 📚 相关文档

- [规划层使用指南](FORENSIC_PLANNER_README.md)
- [执行层使用指南](USER_GUIDE_V2.md)
- [调度器集成架构](SCHEDULER_INTEGRATION_PLAN.md)

---

**最后更新：** 2026-04-10  
**版本：** v2.0
