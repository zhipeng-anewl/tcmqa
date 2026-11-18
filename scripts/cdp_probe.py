# -*- coding: utf-8 -*-
"""用 Chrome DevTools Protocol 驱动页面并执行 JS。

用途：需要「真的点一下」才能验证的交互（双击、导出、图表联动）。
窗口截图只能看到静态结果，这个脚本可以拿运行时状态。

用法：
    python scripts/cdp_probe.py "http://127.0.0.1:8000/#graph?q=枸杞" --expr "document.title"
    python scripts/cdp_probe.py URL --file check.js

实现说明：启动一个带 --remote-debugging-port 的 Chrome，用 HTTP /json 拿到页面
的 websocket 地址，再发 Runtime.evaluate。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import websocket

sys.stdout.reconfigure(encoding="utf-8")

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9333
ROOT = Path(__file__).resolve().parent.parent


def wait_targets(timeout: float = 25.0) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{PORT}/json", timeout=1.0)
            items = [t for t in r.json() if t.get("type") == "page"]
            if items:
                return items
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    raise RuntimeError("Chrome 调试端口没起来")


def evaluate(ws_url: str, expr: str, await_promise: bool = True) -> dict:
    ws = websocket.create_connection(ws_url, timeout=20)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        ws.send(
            json.dumps(
                {
                    "id": 2,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expr,
                        "returnByValue": True,
                        "awaitPromise": await_promise,
                        "userGesture": True,
                    },
                }
            )
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("id") == 2:
                return msg
        raise RuntimeError("等 Runtime.evaluate 结果超时")
    finally:
        ws.close()


def _send(ws, msg_id: int, method: str, params: dict) -> None:
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))


def dispatch_double_click(ws_url: str, x: float, y: float) -> None:
    """用浏览器级输入事件双击 (x, y)。

    JS 里 dispatchEvent(MouseEvent) 到不了 vis-network 的手势层（它用 pointer/触摸事件），
    所以这里改走 CDP 的 Input.dispatchMouseEvent，等价于真人点击。
    """
    ws = websocket.create_connection(ws_url, timeout=20)
    try:
        base = {"x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1}
        for seq_id, (method, extra) in enumerate(
            [
                ("Input.dispatchMouseEvent", {"type": "mousePressed"}),
                ("Input.dispatchMouseEvent", {"type": "mouseReleased", "buttons": 0}),
                ("Input.dispatchMouseEvent", {"type": "mousePressed", "clickCount": 2}),
                ("Input.dispatchMouseEvent", {"type": "mouseReleased", "buttons": 0, "clickCount": 2}),
            ],
            start=100,
        ):
            params = dict(base)
            params.update(extra)
            _send(ws, seq_id, method, params)
            time.sleep(0.05)
        time.sleep(0.4)
    finally:
        ws.close()


def capture_screenshot(ws_url: str, path: str) -> bool:
    """在真实等待之后截图。

    为什么不用 chrome --screenshot：那个只能配 --virtual-time-budget，
    而虚拟时间对 SSE 流式回答不起作用——页面还没渲染完就抓了，
    结果拿到一张骨架屏。这里改为等真实秒数再调 Page.captureScreenshot。
    """
    ws = websocket.create_connection(ws_url, timeout=30)
    try:
        ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
        ws.send(json.dumps({"id": 2, "method": "Page.captureScreenshot",
                            "params": {"format": "png", "captureBeyondViewport": False}}))
        deadline = time.time() + 30
        while time.time() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("id") == 2:
                data = msg.get("result", {}).get("data")
                if not data:
                    return False
                import base64

                Path(path).write_bytes(base64.b64decode(data))
                return True
        return False
    finally:
        ws.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--expr", default="document.title")
    parser.add_argument("--file", default="")
    parser.add_argument("--wait", type=float, default=6.0, help="打开后等待秒数")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument(
        "--dblclick",
        default="",
        help="在可见画布的相对位置双击，格式 fx,fy（0~1），如 0.5,0.4",
    )
    parser.add_argument("--after", type=float, default=3.0, help="双击后再等几秒")
    parser.add_argument(
        "--screenshot",
        default="",
        help="做完上面的动作后再等 --shot-wait 秒，截一张图到指定路径",
    )
    parser.add_argument("--shot-wait", type=float, default=6.0, help="截图前再等几秒")
    args = parser.parse_args()

    expr = Path(args.file).read_text(encoding="utf-8") if args.file else args.expr

    profile = ROOT / ".chrome-profile-cdp"
    profile.mkdir(exist_ok=True)
    cmd = [
        CHROME,
        "--remote-debugging-port=%d" % PORT,
        "--user-data-dir=%s" % profile,
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-crash-reporter",
        "--disable-breakpad",
        "--window-size=1440,1000",
    ]
    if not args.no_headless:
        cmd.append("--headless=new")
        cmd.append("--disable-gpu")
    cmd.append(args.url)

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        targets = wait_targets()
        time.sleep(args.wait)  # 等前端加载与异步请求

        ws_url = targets[0]["webSocketDebuggerUrl"]

        if args.dblclick:
            fx, fy = [float(v) for v in args.dblclick.split(",")]
            # 先问一下可见画布在视口里的位置，再换算成绝对坐标
            box = evaluate(
                ws_url,
                "(() => { const h=[...document.querySelectorAll('.graph-host')]"
                ".filter(x=>x.clientWidth>0)[0]; if(!h) return null;"
                " const r=h.getBoundingClientRect();"
                " return {x:r.left,y:r.top,w:r.width,h:r.height}; })()",
            )
            rect = box.get("result", {}).get("result", {}).get("value")
            if not rect:
                print("找不到可见画布")
                return
            x = rect["x"] + rect["w"] * fx
            y = rect["y"] + rect["h"] * fy
            print(f"双击坐标 ({x:.0f}, {y:.0f})")
            dispatch_double_click(ws_url, x, y)
            time.sleep(args.after)

        result = evaluate(ws_url, expr)
        payload = result.get("result", {})
        if "exceptionDetails" in payload:
            print("JS 异常:", json.dumps(payload["exceptionDetails"], ensure_ascii=False)[:600])
        else:
            value = payload.get("result", {}).get("value")
            if isinstance(value, (dict, list)):
                print(json.dumps(value, ensure_ascii=False, indent=1))
            else:
                print(value)

        if args.screenshot:
            time.sleep(args.shot_wait)
            ok = capture_screenshot(ws_url, args.screenshot)
            print(f"截图{'成功' if ok else '失败'}：{args.screenshot}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
