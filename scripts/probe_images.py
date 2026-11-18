# -*- coding: utf-8 -*-
"""核对图谱里的 image_path 与实际文件是否对得上，并统计缺口。"""

from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402
from tcmqa.settings import settings  # noqa: E402

# 原始图片不在仓库内，路径由环境变量 HERB_IMAGE_ROOT / MOL_IMAGE_ROOT 指定
if not settings.herb_image_root:
    sys.exit("缺少 HERB_IMAGE_ROOT：请在 .env 里指向原始中药图片目录（见 .env.example）")
HERB_ROOT = Path(settings.herb_image_root)
MOL_ROOT = Path(settings.mol_image_root or "").parent


def main() -> None:
    with GraphClient() as c:
        herbs = c.read(
            "MATCH (h:Herb) RETURN h.id AS id, h.name AS name, h.image_path AS p", limit=2000
        )
        ings = c.read(
            "MATCH (i:Ingredient) RETURN i.id AS id, i.name AS name, "
            "i.structure_image_path AS p", limit=20000
        )

    print("== Herb 样例")
    for r in herbs[:5]:
        print("  ", r["id"], r["name"], "|", r["p"])

    print("\n== Ingredient 样例")
    for r in ings[:5]:
        print("  ", r["id"], r["name"], "|", r["p"])

    # 中药：路径形如 herb_images\矮地茶\HER0001_1.jpg
    herb_missing = []
    herb_ok = 0
    for r in herbs:
        p = r.get("p")
        if not p:
            herb_missing.append((r["id"], r["name"], "无 image_path"))
            continue
        full = HERB_ROOT / str(p).replace("\\", "/")
        if full.exists():
            herb_ok += 1
        else:
            herb_missing.append((r["id"], r["name"], str(p)))
    print(f"\n== Herb 文件核对: 存在 {herb_ok} / 缺失 {len(herb_missing)}")
    for m in herb_missing[:8]:
        print("   缺失:", m)

    mol_missing = []
    mol_ok = 0
    for r in ings:
        p = r.get("p")
        if not p:
            mol_missing.append((r["id"], r["name"], "无 structure_image_path"))
            continue
        full = MOL_ROOT / str(p).replace("\\", "/")
        if full.exists():
            mol_ok += 1
        else:
            mol_missing.append((r["id"], r["name"], str(p)))
    print(f"\n== Ingredient 文件核对: 存在 {mol_ok} / 缺失 {len(mol_missing)}")
    for m in mol_missing[:8]:
        print("   缺失:", m)

    # 每味药有几张图
    per_herb = Counter()
    for r in herbs:
        p = r.get("p")
        if not p:
            continue
        folder = (HERB_ROOT / str(p).replace("\\", "/")).parent
        if folder.exists():
            per_herb[r["id"]] = len([f for f in folder.iterdir() if f.is_file()])
    if per_herb:
        counts = list(per_herb.values())
        print(f"\n== 每味药图片数: 最少 {min(counts)} 最多 {max(counts)} "
              f"平均 {sum(counts)/len(counts):.1f}")

    # 图片尺寸抽样
    from PIL import Image

    print("\n== 尺寸抽样")
    for r in herbs[:3]:
        p = r.get("p")
        if not p:
            continue
        full = HERB_ROOT / str(p).replace("\\", "/")
        if full.exists():
            with Image.open(full) as im:
                print("   herb", full.name, im.size, im.mode,
                      f"{full.stat().st_size/1024:.0f}KB")
    for r in ings[:3]:
        p = r.get("p")
        if not p:
            continue
        full = MOL_ROOT / str(p).replace("\\", "/")
        if full.exists():
            with Image.open(full) as im:
                print("   mol ", full.name, im.size, im.mode,
                      f"{full.stat().st_size/1024:.0f}KB")


if __name__ == "__main__":
    main()
