#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Antigravity 2.0 无侵入 CDP 动态汉化插件（纯 Python 标准库）。"""

import sys

sys.dont_write_bytecode = True

import argparse
import base64
import json
import os
import signal
import socket
import struct
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DICT_PATH = ROOT / "dict.json"
INJECT_PATH = ROOT / "inject.js"
MISSING_PATH = ROOT / "missing-terms.json"
INJECT_VERSION = "0.7.0"


def load_dictionary():
    data = json.loads(DICT_PATH.read_text(encoding="utf-8"))
    exact = data.get("exact", {})
    return {str(k): str(v) for k, v in exact.items() if isinstance(k, str) and isinstance(v, str)}


def load_inject_script():
    return INJECT_PATH.read_text(encoding="utf-8")


def find_antigravity_listen_ports():
    """在 Windows 上查找 Antigravity 进程监听的 127.0.0.1 端口。"""
    ports = []
    try:
        pids_raw = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq Antigravity.exe", "/FO", "CSV", "/NH"],
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        pids = set()
        for line in pids_raw.splitlines():
            parts = [p.strip('"') for p in line.split(",")]
            if len(parts) >= 2 and parts[1].isdigit():
                pids.add(parts[1])
        if not pids:
            return []

        net_raw = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"],
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        for line in net_raw.splitlines():
            cols = line.split()
            if len(cols) >= 5 and cols[0] == "TCP" and cols[3] == "LISTENING":
                addr, pid = cols[1], cols[4]
                if pid in pids and addr.startswith("127.0.0.1:"):
                    port_str = addr.rsplit(":", 1)[-1]
                    if port_str.isdigit():
                        p = int(port_str)
                        if p not in ports:
                            ports.append(p)
    except Exception:
        pass
    return ports


def fetch_cdp_targets(port, timeout=1.5):
    url = f"http://127.0.0.1:{port}/json/list"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    targets = json.loads(raw)
    if not isinstance(targets, list):
        return []
    return [
        t for t in targets
        if isinstance(t, dict)
        and t.get("webSocketDebuggerUrl")
        and t.get("type") in ("page", "webview", "app", "iframe", None)
        and not str(t.get("url", "")).startswith("data:")
    ]


def discover_cdp(explicit_port=None):
    candidates = [explicit_port] if explicit_port else find_antigravity_listen_ports()
    for port in candidates:
        try:
            targets = fetch_cdp_targets(port)
            if targets:
                return port, targets
        except Exception:
            continue
    return None, []


class SimpleWS:
    """最小纯标准库 RFC 6455 WebSocket 客户端（仅用于本机 127.0.0.1 CDP）。"""

    def __init__(self, ws_url, timeout=5.0):
        parsed = urlparse(ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode("ascii"))
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake closed")
            buf += chunk
        status_line = buf.split(b"\r\n", 1)[0]
        if b"101" not in status_line:
            raise ConnectionError(f"WebSocket upgrade failed: {status_line!r}")

    def _recv_exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("WebSocket closed unexpectedly")
            buf.extend(chunk)
        return bytes(buf)

    def send_text(self, text):
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv_text(self):
        chunks = []
        while True:
            b1, b2 = self._recv_exact(2)
            fin = (b1 & 0x80) != 0
            opcode = b1 & 0x0F
            masked = (b2 & 0x80) != 0
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else None
            data = self._recv_exact(length) if length else b""
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:
                raise ConnectionError("WebSocket closed by peer")
            if opcode == 0x9:
                continue
            chunks.append(data)
            if fin:
                return b"".join(chunks).decode("utf-8", errors="replace")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def cdp_eval(ws_url, expression, timeout=4.0):
    ws = SimpleWS(ws_url, timeout=timeout)
    try:
        msg = json.dumps(
            {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": expression, "returnByValue": True},
            }
        )
        ws.send_text(msg)
        while True:
            reply = json.loads(ws.recv_text())
            if reply.get("id") == 1:
                result = reply.get("result", {}).get("result", {})
                return result.get("value")
    finally:
        ws.close()


def apply_to_targets(targets, inject_code, dict_map):
    dict_json = json.dumps(dict_map, ensure_ascii=False)
    expr = (
        f"(() => {{ if (!window.__agZhCn || window.__agZhCn.version !== '{INJECT_VERSION}') {{ "
        f"if (window.__agZhCn && window.__agZhCn.restore) {{ window.__agZhCn.restore(); }} "
        f"delete window.__agZhCn; {inject_code} }} "
        f"return window.__agZhCn.apply({dict_json}); }})()"
    )
    results = []
    for t in targets:
        title = t.get("title") or t.get("url") or t.get("id")
        try:
            res = cdp_eval(t["webSocketDebuggerUrl"], expr)
            results.append((title, res))
        except Exception as exc:
            results.append((title, {"error": str(exc)}))
    return results


def restore_targets(targets):
    expr = "(() => window.__agZhCn ? window.__agZhCn.restore() : {status: 'not_injected'})()"
    results = []
    for t in targets:
        title = t.get("title") or t.get("url") or t.get("id")
        try:
            res = cdp_eval(t["webSocketDebuggerUrl"], expr, timeout=1.5)
            results.append((title, res))
        except Exception as exc:
            results.append((title, {"error": str(exc)}))
    return results


def dump_targets(targets, inject_code, dict_map):
    expr = (
        f"(() => {{ if (!window.__agZhCn) {{ {inject_code} }} "
        f"return window.__agZhCn.dumpTexts(); }})()"
    )
    found = set()
    for t in targets:
        try:
            items = cdp_eval(t["webSocketDebuggerUrl"], expr) or []
            for item in items:
                if item not in dict_map:
                    found.add(item)
        except Exception:
            continue
    return sorted(found)


def collect_missing_from_targets(targets, dict_map):
    expr = "(() => window.__agZhCn && window.__agZhCn.takeMissing ? window.__agZhCn.takeMissing() : [])()"
    incoming = set()
    for t in targets:
        try:
            items = cdp_eval(t["webSocketDebuggerUrl"], expr, timeout=2.0) or []
            for item in items:
                if isinstance(item, str) and item not in dict_map:
                    incoming.add(item)
        except Exception:
            continue
    if not incoming:
        return 0

    existing = {}
    if MISSING_PATH.is_file():
        try:
            raw = json.loads(MISSING_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = {str(k): str(v) for k, v in raw.items() if k not in dict_map}
        except Exception:
            existing = {}

    added = 0
    for term in sorted(incoming):
        if term not in existing:
            existing[term] = ""
            added += 1

    if added > 0:
        MISSING_PATH.write_text(
            json.dumps(dict(sorted(existing.items())), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return added


def prune_missing_file(dict_map):
    if not MISSING_PATH.is_file():
        return 0
    try:
        raw = json.loads(MISSING_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return 0
        kept = {str(k): str(v) for k, v in raw.items() if k not in dict_map}
        removed = len(raw) - len(kept)
        if removed > 0:
            MISSING_PATH.write_text(
                json.dumps(dict(sorted(kept.items())), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return removed
    except Exception:
        return 0


def watch_loop(explicit_port=None):
    running = True

    def _stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    dict_map = load_dictionary()
    inject_code = load_inject_script()
    last_dict_mtime = DICT_PATH.stat().st_mtime
    seen_urls = set()
    last_collect = 0.0
    active_port = explicit_port
    started_at = time.monotonic()
    warned_no_port = False

    print("antigravity-zh-cn Sidecar 监听已启动...", flush=True)
    while running:
        sleep_sec = 2.0
        try:
            cur_mtime = DICT_PATH.stat().st_mtime
            if cur_mtime != last_dict_mtime:
                dict_map = load_dictionary()
                last_dict_mtime = cur_mtime
                seen_urls.clear()
                prune_missing_file(dict_map)
                print(f"检测到 dict.json 更新（{len(dict_map)} 条），准备热重载...", flush=True)

            port, cur_targets = discover_cdp(active_port)
            if not port and active_port and not explicit_port:
                active_port = None
                port, cur_targets = discover_cdp(None)
            if port:
                active_port = port
                warned_no_port = False
                pending = [t for t in cur_targets if t.get("webSocketDebuggerUrl") not in seen_urls]
                if pending:
                    for t, (title, res) in zip(pending, apply_to_targets(pending, inject_code, dict_map)):
                        if isinstance(res, dict) and res.get("status") == "applied":
                            seen_urls.add(t["webSocketDebuggerUrl"])
                            print(f"[{title}] -> {res}", flush=True)

                now = time.monotonic()
                if now - last_collect >= 10.0 and cur_targets:
                    added = collect_missing_from_targets(cur_targets, dict_map)
                    if added > 0:
                        print(f"收集到 {added} 条未汉化新词条，已写入 {MISSING_PATH.name}", flush=True)
                    last_collect = now
            else:
                if not warned_no_port and time.monotonic() - started_at >= 10.0:
                    warned_no_port = True
                    print(
                        "提示：暂未检测到 CDP 调试端口（请确认启动参数含 --remote-debugging-port=0 --remote-debugging-address=127.0.0.1），已降频静默等待。",
                        flush=True,
                    )
                sleep_sec = 5.0
        except Exception as exc:
            print(f"监听轮询异常: {exc}", flush=True)

        time.sleep(sleep_sec)

    # 退出时尽量还原界面英文
    try:
        _, cur_targets = discover_cdp(active_port)
        if cur_targets:
            restore_targets(cur_targets)
    except Exception:
        pass
    print("antigravity-zh-cn Sidecar 已停止。", flush=True)
    return 0


def patch_windows_shortcuts():
    """为桌面和开始菜单中的 Antigravity 快捷方式追加本机回环调试参数。"""
    ps_script = r"""
$flags = '--remote-debugging-port=0 --remote-debugging-address=127.0.0.1'
$roots = @(
  [Environment]::GetFolderPath('Desktop'),
  [Environment]::GetFolderPath('Programs'),
  (Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar')
)
$shell = New-Object -ComObject WScript.Shell
$patched = @()
foreach ($r in $roots) {
  if (-not $r -or -not (Test-Path $r)) { continue }
  Get-ChildItem -Path $r -Filter '*Antigravity*.lnk' -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
    $sc = $shell.CreateShortcut($_.FullName)
    if ($sc.TargetPath -and ($sc.TargetPath -match 'Antigravity\.exe$')) {
      $cur = [string]$sc.Arguments
      if ($cur -notmatch '--remote-debugging-port=') {
        $sc.Arguments = (($cur.Trim() + ' ' + $flags).Trim())
        $sc.Save()
        $patched += $_.FullName
      }
    }
  }
}
$patched | ForEach-Object { Write-Output $_ }
"""
    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    paths = [line.strip() for line in out.splitlines() if line.strip()]
    if paths:
        print("已为以下快捷方式添加调试参数（重启 Antigravity 后生效）：")
        for p in paths:
            print(f"  - {p}")
    else:
        print("未找到需要修改的 Antigravity 快捷方式（可能已包含调试参数，或快捷方式位于其他路径）。")
    return 0


def check_port_hook():
    """SessionStart 钩子：端口正常时静默返回 {}，未开启时输出简短提示。"""
    port, _ = discover_cdp(None)
    if port:
        print("{}")
    else:
        msg = (
            "[antigravity-zh-cn] 未检测到调试端口，动态汉化暂未生效。"
            "请确认启动快捷方式包含 --remote-debugging-port=0 --remote-debugging-address=127.0.0.1"
            "（或运行 python -B zh_cn.py --patch-shortcut 后重启客户端）。"
        )
        print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Antigravity 2.0 无侵入动态汉化（Windows）")
    parser.add_argument("--port", type=int, default=None, help="手动指定 CDP 调试端口")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="查看调试端口与可用页面")
    group.add_argument("--once", action="store_true", help="注入一次汉化并退出")
    group.add_argument("--watch", action="store_true", help="常驻监听并自动汉化新页面与收集新词条")
    group.add_argument("--restore", action="store_true", help="还原页面原始英文文案")
    group.add_argument("--dump-texts", action="store_true", help="提取未汉化的 UI 短文本")
    group.add_argument("--check-port", action="store_true", help="SessionStart 端口静默检测钩子")
    group.add_argument("--patch-shortcut", action="store_true", help="为 Windows 快捷方式添加调试启动参数")
    args = parser.parse_args()

    if not any([args.status, args.once, args.watch, args.restore, args.dump_texts, args.check_port, args.patch_shortcut]):
        args.status = True

    if args.check_port:
        return check_port_hook()

    if args.patch_shortcut:
        return patch_windows_shortcuts()

    if args.watch:
        return watch_loop(args.port)

    port, targets = discover_cdp(args.port)
    if not port:
        print("未检测到带调试端口的 Antigravity 2.0 渲染页面。")
        print("请确保 Antigravity 启动参数包含：")
        print("  --remote-debugging-port=0 --remote-debugging-address=127.0.0.1")
        return 1

    if args.status:
        print(f"已发现 CDP 调试端口: 127.0.0.1:{port}（共 {len(targets)} 个页面）")
        for t in targets:
            print(f"  - [{t.get('type')}] {t.get('title') or '(无标题)'} | {t.get('url')}")
        return 0

    if args.restore:
        for title, res in restore_targets(targets):
            print(f"[{title}] -> {res}")
        return 0

    dict_map = load_dictionary()
    inject_code = load_inject_script()

    if args.dump_texts:
        missing = dump_targets(targets, inject_code, dict_map)
        print(f"共提取到 {len(missing)} 条尚未在 dict.json 中的 UI 短文本：")
        for item in missing:
            print(f"  {json.dumps(item, ensure_ascii=False)}: \"\",")
        return 0

    if args.once:
        for title, res in apply_to_targets(targets, inject_code, dict_map):
            print(f"[{title}] -> {res}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
