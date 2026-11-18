# -*- coding: utf-8 -*-
"""检查运行中的服务是否托管了最新的前端构建产物。

只做静态验证：首页可访问、入口 JS/CSS 可下载、bundle 里包含关键文案。
（真正的视觉检查得用浏览器，脚本替代不了。）
"""

from __future__ import annotations

import re
import sys

import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
MARKERS = ["岐黄问答", "从一味药", "能做什么", "拍照识药", "知识图谱", "运行指标", "免责声明"]


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        home = c.get("/")
        print(f"GET / -> {home.status_code}, {len(home.content)} bytes")
        if home.status_code != 200:
            print("首页不可用")
            return

        html = home.text
        js = re.search(r'src="(/assets/[^"]+\.js)"', html)
        css = re.search(r'href="(/assets/[^"]+\.css)"', html)
        print(f"入口 JS : {js.group(1) if js else '未找到'}")
        print(f"入口 CSS: {css.group(1) if css else '未找到'}")

        if js:
            bundle = c.get(js.group(1))
            print(f"  JS {bundle.status_code}, {len(bundle.content) / 1024:.1f} KB")
            text = bundle.text
            for kw in MARKERS:
                print(f"    {'✓' if kw in text else '✗'} {kw}")

        if css:
            sheet = c.get(css.group(1))
            print(f"  CSS {sheet.status_code}, {len(sheet.content) / 1024:.1f} KB")
            css_text = sheet.text
            for kw in ["--jade", "--paper", "appbar", "stat-card", "feature-card"]:
                print(f"    {'✓' if kw in css_text else '✗'} {kw}")

        health = c.get("/api/health").json()
        print(f"API 健康: {health['status']}")


if __name__ == "__main__":
    main()
