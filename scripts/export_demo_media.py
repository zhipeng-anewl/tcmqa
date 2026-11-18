# -*- coding: utf-8 -*-
"""把演示版 fixture 引用到的图片抽出来，放进 frontend/public/media。

静态托管没有后端 ／media 路由，图片必须自带。
只复制**实际被引用**的那些（药材封面 / 图库缩略图 / 分子结构式），
不是把 2875 张全打包。

产物：
    frontend/public/media/covers/*.webp
    frontend/public/media/gallery/*.webp
    frontend/public/media/mol/*.png
    frontend/public/demo/media.json   名称 -> 图片信息（替代 /api/media/resolve）
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.settings import settings  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "frontend" / "demo-public" / "demo"
PUBLIC_MEDIA = ROOT / "frontend" / "demo-public" / "media"

# URL 前缀 -> 本地源目录（原始素材不在仓库内，路径来自环境变量）
SOURCES = {
    "/media/covers/": ROOT / "data" / "images" / "herb",
    "/media/gallery/": ROOT / "data" / "images" / "herb_gallery",
    "/media/mol/": Path(settings.mol_image_root or ""),
}

# 产物子目录（public 下）
TARGETS = {
    "/media/covers/": PUBLIC_MEDIA / "covers",
    "/media/gallery/": PUBLIC_MEDIA / "gallery",
    "/media/mol/": PUBLIC_MEDIA / "mol",
}


def collect_names() -> set[str]:
    """从问答 fixture 里收集所有可能被配图的实体名。"""
    names: set[str] = set()
    for f in (DEMO / "qa").glob("*.json"):
        for ev in json.loads(f.read_text(encoding="utf-8")):
            if ev.get("type") != "evidence":
                continue
            for item in ev.get("data") or []:
                if item.get("kind") in ("herb", "ingredient") and item.get("title"):
                    names.add(item["title"])
                payload = item.get("payload") or {}
                for key in ("ingredient", "herb"):
                    val = payload.get(key)
                    if isinstance(val, str) and val:
                        names.add(val)
    return names


def copy_file(url: str) -> bool:
    for prefix, src_dir in SOURCES.items():
        if not url.startswith(prefix):
            continue
        filename = url[len(prefix):]
        src = src_dir / filename
        if not src.exists():
            return False
        dst = TARGETS[prefix] / filename
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    return False


def main() -> None:
    names = sorted(collect_names())
    print(f"fixture 里出现的实体名：{len(names)} 个")

    resolved: dict[str, dict] = {}
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=120) as client:
        for i in range(0, len(names), 40):
            batch = names[i : i + 40]
            try:
                data = client.get(
                    "/api/media/resolve", params={"names": ",".join(batch)}
                ).json()
                resolved.update(data.get("items") or {})
            except Exception as exc:  # noqa: BLE001
                print(f"  解析失败（{i}）：{exc}")

    # 识药 fixture 里直接给了 cover
    extra_urls: set[str] = set()
    for f in sorted((DEMO / "vision").glob("*.json")):
        for item in json.loads(f.read_text(encoding="utf-8")).get("results") or []:
            if item.get("cover"):
                extra_urls.add(item["cover"])

    copied = 0
    missing_src: list[tuple[str, str]] = []
    for name, item in resolved.items():
        for url in (item.get("thumb") or "", item.get("orig") or ""):
            if not url:
                continue
            if copy_file(url):
                copied += 1
            else:
                missing_src.append((name, url))
    for url in extra_urls:
        if copy_file(url):
            copied += 1

    if missing_src:
        print(f"源文件缺失 {len(missing_src)} 条（这些实体的配图会被跳过）：")
        for name, url in missing_src[:10]:
            print(f"  {name} -> {url}")

    # 只保留图片确实存在的条目，避免前端拿着 404 地址
    keep = {}
    for name, item in resolved.items():
        thumb = item.get("thumb") or ""
        local = next((p for p in SOURCES if thumb.startswith(p)), None)
        if local and (TARGETS[local] / thumb[len(local):]).exists():
            keep[name] = item

    (DEMO / "media.json").write_text(
        json.dumps({"items": keep}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    total = sum(f.stat().st_size for f in PUBLIC_MEDIA.rglob("*") if f.is_file())
    files = sum(1 for f in PUBLIC_MEDIA.rglob("*") if f.is_file())
    print(f"复制图片 {files} 个，共 {total / 1024 / 1024:.1f} MB")
    print(f"media.json：{len(keep)} 个实体有配图")


if __name__ == "__main__":
    main()
