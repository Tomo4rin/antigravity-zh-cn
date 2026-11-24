---
name: antigravity-zh-cn
description: 补全、更新或排查 Antigravity 简体中文动态汉化词典。当用户说“补全汉化词条”、“把漏网词条翻译一下”、“更新汉化词典”或询问汉化插件状态时使用。
---

# Antigravity 简体中文动态汉化维护技能

## 插件文件位置

- 已安装插件目录：`C:\Users\<用户名>\.gemini\config\plugins\antigravity-zh-cn\`
- 核心文件：
  - `dict.json`：中英精确词典（`exact` 字段）
  - `missing-terms.json`：Sidecar 运行时自动去重收集的未翻译 UI 控件文本
  - `zh_cn.py`：主控脚本（Sidecar `--watch` 模式下会监测 `dict.json` 修改时间并在 2 秒内自动热重载，同时自动清理 `missing-terms.json` 中已翻译的词条）

## 补全漏网词条流程

1. 读取插件目录下的 `missing-terms.json`。
2. 过滤掉明显属于代码片段、路径、模型名或无需汉化的专有名词。
3. 将需要汉化的词条精准翻译为地道简体中文，合并写入同目录的 `dict.json`（`exact` 对象）。
4. 若 Sidecar 正在运行，无需重启客户端，2 秒内会自动热重载到界面并清理 `missing-terms.json`；若未运行 Sidecar，可提示用户或执行 `python -B zh_cn.py --once`。
