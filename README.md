# Antigravity 简体中文汉化插件（antigravity-zh-cn）

> 适用平台：**Windows（Antigravity 2.0 桌面端）** + **Python 3.10+**  
> 特点：**零第三方依赖** · **不修改 `app.asar` 或客户端安装目录** · **支持词典热更新与漏词自动收集**

## 原理说明

通过 Antigravity Sidecar 机制在后台自动监听本机回环调试端口（CDP），向渲染页面注入轻量的 `MutationObserver` 词典翻译器：
- 仅翻译精确匹配的 UI 控件与设置文案，自动跳过代码块（`pre`/`code`）、终端与对话输入区；
- 检测到未收录的新英文 UI 控件时，自动去重记录到 `missing-terms.json`；
- 支持一键无损还原为原始英文，并在修改 `dict.json` 后 2 秒内自动热更新。

## 安装步骤（Windows）

1. 将本仓库目录复制到插件目录：
   ```text
   %USERPROFILE%\.gemini\config\plugins\antigravity-zh-cn\
   ```
2. 为 Antigravity 快捷方式添加本机回环调试参数（仅需配置一次）：
   ```powershell
   python -B zh_cn.py --patch-shortcut
   ```
   *(或手动在快捷方式“目标”末尾追加 `--remote-debugging-port=0 --remote-debugging-address=127.0.0.1`)*
3. 在 Antigravity 的 **Customizations → Plugins** 中确认启用 **`Antigravity 简体中文汉化`**，完全退出并重启客户端即可自动生效。

## 目录结构

- `plugin.json` & `assets/logo.svg`：Antigravity 插件清单与图标
- `sidecars/zh-cn/sidecar.json`：Sidecar 常驻服务声明
- `hooks.json`：SessionStart 静默检测（仅当未检测到调试端口时提示用户）
- `zh_cn.py`：Python 纯标准库主控脚本
- `inject.js`：前端 DOM 翻译器与漏词增量收集器（内置 React 节点原地更新识别与 17 条动态规则，支持最高 800 字符的斜杠命令与技能说明精确匹配，实时同步思考强度、计时、工具计数、Swarm 面板与权限弹窗）
- `dict.json`：中英精确 UI 词典（1045 条）
- `skills/antigravity-zh-cn/SKILL.md`：配合 Agent 一键补全 `missing-terms.json` 的技能说明

## 常用命令行

```powershell
python -B zh_cn.py --status          # 检查调试端口与可注入页面
python -B zh_cn.py --once            # 单次注入汉化
python -B zh_cn.py --watch           # 常驻监听（Sidecar 默认模式）
python -B zh_cn.py --restore         # 一键无损还原英文
python -B zh_cn.py --dump-texts      # 立即提取当前页未汉化 UI 短文本
python -B zh_cn.py --patch-shortcut  # 自动为 Windows 快捷方式添加调试参数
```

## 开源协议

[MIT](LICENSE)
