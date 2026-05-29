# ForensiFlow 模块级测试入口

本文档记录正式实验前建议使用的模块级测试入口。

## 1. 规划层单独测试

只生成取证规划，不执行手机 UI 动作：

```bash
python auto_forensic_planning.py \
  --skip-app-extract \
  --mapping-file data/app_info/package_name_mapping.txt \
  --case "案件背景..." \
  --goals "提取 WhatsApp 通话记录"
```

输出规划会写入配置的 plans 目录。

## 2. Codex 探索 Agent 测试

先使用 dry-run 检查命令和 prompt，不触碰手机：

```bash
python tools/run_codex_forensiflow_full_agent.py \
  --device-serial <serial> \
  --package-name com.whatsapp \
  --app-name WhatsApp \
  --target "提取所有通话记录" \
  --dry-run
```

真实执行时移除 `--dry-run`。真实执行会控制已连接手机，并运行 Codex 探索、脚本生成、脚本运行和修复流程。

## 3. 经验复用模块单独测试

经验复用模块测试入口只允许选择 RAG 模板库中已有的任务。

列出可运行模板：

```bash
python tools/test_experience_reuse.py --list
```

只选择模板，不触碰手机：

```bash
python tools/test_experience_reuse.py \
  --app-name WhatsApp \
  --task "提取所有通话记录" \
  --json
```

执行已选择的复用模板：

```bash
python tools/test_experience_reuse.py \
  --app-name WhatsApp \
  --task "提取所有通话记录" \
  --device-serial <serial> \
  --execute
```

## 4. 单任务直达调度器测试

用于跳过规划层，把一个任务直接送入 Route Selector，让系统自动决定走经验复用还是 Codex 探索。默认只做路由选择，不触碰手机。

只测试路由选择：

```bash
python tools/test_direct_scheduler.py \
  --app-name WhatsApp \
  --package-name com.whatsapp \
  --task "提取所有通话记录" \
  --json
```

真实执行：

```bash
python tools/test_direct_scheduler.py \
  --app-name WhatsApp \
  --package-name com.whatsapp \
  --task "提取所有通话记录" \
  --device-serial <serial> \
  --execute
```

如果 Route Selector 选择复用路径，命中的模板必须是 RAG 模板库中的可运行模板。如果选择探索路径，真实执行时必须提供 `--package-name`。

## 5. 全流程实验入口

用于验证“规划层 → 路由选择 → 复用/探索执行”的完整链路。

只做规划和路由，不触碰手机：

```bash
python tools/test_end_to_end_flow.py \
  --selection-only \
  --max-apps 1 \
  --max-tasks-per-app 1 \
  --json
```

连接设备后真实执行：

```bash
python tools/test_end_to_end_flow.py \
  --device-serial <serial> \
  --execute \
  --max-apps 1 \
  --max-tasks-per-app 1 \
  --json
```

正式入口也支持同样参数：

```bash
python run_end_to_end.py \
  --device-serial <serial> \
  --case "..." \
  --goals "..." \
  --selection-only \
  --max-apps 1 \
  --max-tasks-per-app 1
```
