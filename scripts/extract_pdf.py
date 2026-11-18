# -*- coding: utf-8 -*-
"""提取 PDF 文本（用于读论文）。

用法：
    python scripts/extract_pdf.py "C:\\path\\to\\paper.pdf" --pages 1-6
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pypdf import PdfReader


def parse_range(spec: str, total: int) -> range:
    if not spec:
        return range(0, min(total, 5))
    start, _, end = spec.partition("-")
    lo = max(1, int(start)) - 1
    hi = int(end) if end else lo + 1
    return range(lo, min(hi, total))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--pages", default="1-5")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    path = Path(args.pdf)
    if not path.exists():
        print(f"文件不存在：{path}")
        sys.exit(1)

    reader = PdfReader(str(path))
    total = len(reader.pages)
    print(f"总页数 {total}")

    chunks = []
    for i in parse_range(args.pages, total):
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            text = f"[第 {i + 1} 页提取失败：{exc}]"
        chunks.append(f"\n===== 第 {i + 1} 页 =====\n{text}")

    body = "".join(chunks)
    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
        print(f"已写入 {args.out}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(body)


if __name__ == "__main__":
    main()
