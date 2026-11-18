# -*- coding: utf-8 -*-
"""单独排查流式接口：打印事件序列与增量文本。"""

from __future__ import annotations

import json
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=180.0) as client:
        question = "黄芪有什么功效？"
        print("问题:", question)

        events: list[dict] = []
        text = ""
        t0 = time.perf_counter()
        with client.stream("POST", "/api/chat/stream",
                           json={"question": question, "use_cache": False}) as resp:
            print("状态码:", resp.status_code)
            buffer = ""
            for chunk in resp.iter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    raw, buffer = buffer.split("\n\n", 1)
                    line = next((l for l in raw.split("\n") if l.startswith("data:")), None)
                    if not line:
                        continue
                    event = json.loads(line[5:].strip())
                    events.append(event)
                    if event["type"] == "token":
                        text += event["data"]

        print(f"耗时 {(time.perf_counter() - t0) * 1000:.0f}ms")
        print("事件类型:", [e["type"] for e in events])
        print(f"token 事件数: {sum(1 for e in events if e['type'] == 'token')}")
        print(f"文本长度: {len(text)}")
        print("文本:", repr(text[:200]))

        for e in events:
            if e["type"] in ("error", "done"):
                data = e["data"]
                if isinstance(data, dict):
                    print(f"  [{e['type']}] intent={data.get('intent')} "
                          f"evidence={len(data.get('evidence', []))} "
                          f"answer_len={len(data.get('answer', ''))}")
                else:
                    print(f"  [{e['type']}] {data}")


if __name__ == "__main__":
    main()
