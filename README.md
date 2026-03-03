# MobiAgent

Android UI 自动化框架，结合 ForensiVision 视觉检测和 LLM 任务规划。

## ✨ 特性

- 🎯 **智能任务规划**: LLM 自动拆解复杂任务为执行步骤
- 📱 **多设备支持**: Android (真机/模拟器)
- 🚀 **双重匹配策略**: XML 快速匹配 + ForensiVision 视觉检测
- 🤖 **多 LLM 支持**: Qwen (通义千问)、ChatGLM (智谱 AI)

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 下载模型

将 ForensiVision 模型文件放到：
```
~/models/ForensiVision/pt_model/
├── yolo_mdl.pt
├── yolo_vins_14_mdl.pt
├── clip_mdl.pth
└── clip_labels/
```

### 3. 配置 API Key

创建 `.env` 文件：
```bash
QWEN_API_KEY=sk-xxxxx  # 或 CHATGLM_API_KEY
```

### 4. 连接设备

```bash
# 查看 ADB 设备
adb devices

# 连接设备
adb connect <IP>:<PORT>
```

### 5. 运行

```bash
python run_project.py
```

## 📖 详细文档

完整使用说明请查看 [NOTES.md](NOTES.md)

## 📁 项目结构

```
MobiAgent/
├── runner/mobiagent/      # 核心代码
├── external/ForensiVision/ # ForensiVision UI 检测
├── data/                  # 运行数据输出
├── run_project.py         # 启动脚本
└── requirements.txt       # 依赖列表
```

## 🎯 执行模式

### 步骤序列模式（推荐）

```python
scheduler.run_task(
    app="自动检测",
    old_task="打开微信朋友圈",
    task="打开微信朋友圈",
    use_abstract_task=True  # LLM 预规划 + XML 优先
)
```

**流程**: LLM 规划 → 步骤序列 → 逐步执行（XML 优先，失败则 ForensiVision）

### 逐步决策模式

```python
scheduler.run_task(
    app="微信",
    task="打开朋友圈",
    use_abstract_task=False  # 每步都截图 + 检测 + LLM 决策
)
```

## ⚡ 性能对比

| 匹配方式 | 速度 | 准确率 |
|---------|------|--------|
| XML 匹配 | < 100ms | 95% |
| ForensiVision + LLM | ~5s | 99% |

## 📝 示例

**输入任务**: "打开微信朋友圈"

**LLM 规划**:
```json
{
  "steps": [
    {"action": "click", "target": "发现"},
    {"action": "click", "target": "朋友圈"}
  ]
}
```

**执行过程**:
```
步骤 1/2: 点击"发现"
  ✅ XML 匹配成功 → 点击 (540, 200)

步骤 2/2: 点击"朋友圈"
  ❌ XML 匹配失败
  🔄 ForensiVision 检测 + LLM 决策 → 点击 (540, 350)
```

## 🔧 常见问题

详见 [NOTES.md](NOTES.md#常见问题)

## 📄 许可证

Apache 2.0
