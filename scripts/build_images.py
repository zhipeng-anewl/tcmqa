# -*- coding: utf-8 -*-
"""为图谱实体生成可直接给浏览器用的图片资源。

为什么需要这一步：
- 中药原图平均 200KB，2,876 张共 1.13GB，直接塞给前端会拖死首屏；
- 分子结构图本来就只有 2~14KB，重编码反而变大，直接发原图更划算。

所以策略是分开的：
- 中药 → 每味药取第一张，生成 480px 的 webp 封面，约 25KB/张；
- 分子 → 不转换，交给静态目录直接发原图。

产物：
    data/images/herb/{HER0001}.webp      封面
    data/images/manifest.json            构建统计与缺失清单

用法：
    python scripts/build_images.py
    python scripts/build_images.py --force   # 覆盖已存在的
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from tcmqa.kg.client import GraphClient  # noqa: E402
from tcmqa.settings import DATA_DIR, settings  # noqa: E402

# 原始图片不在仓库内，路径由环境变量 HERB_IMAGE_ROOT / MOL_IMAGE_ROOT 指定
if not settings.herb_image_root:
    sys.exit("缺少 HERB_IMAGE_ROOT：请在 .env 里指向原始中药图片目录（见 .env.example）")
HERB_SRC = Path(settings.herb_image_root)
MOL_SRC = Path(settings.mol_image_root or "")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
OUT_DIR = DATA_DIR / "images"
HERB_OUT = OUT_DIR / "herb"
GALLERY_OUT = OUT_DIR / "herb_gallery"

COVER_SIZE = 480
GALLERY_SIZE = 200
WEBP_QUALITY = 82
GALLERY_QUALITY = 78


def _open_rgb(path: Path) -> Image.Image:
    """统一成 RGB：分子图/部分中药图是 RGBA 或调色板模式，webp 封面要压白底。"""
    with Image.open(path) as im:
        im.load()
        if im.mode in ("RGBA", "LA", "P"):
            rgba = im.convert("RGBA")
            canvas = Image.new("RGB", rgba.size, (255, 255, 255))
            canvas.paste(rgba, mask=rgba.split()[-1])
            return canvas
        return im.convert("RGB")


def build_herb_covers(force: bool = False) -> dict:
    HERB_OUT.mkdir(parents=True, exist_ok=True)
    with GraphClient() as client:
        rows = client.read(
            "MATCH (h:Herb) RETURN h.id AS id, h.name AS name, h.image_path AS path",
            limit=2000,
        )

    built, skipped, missing, failed = 0, 0, [], []
    total_bytes = 0

    for row in rows:
        herb_id = str(row.get("id") or "")
        rel = row.get("path")
        if not herb_id or not rel:
            missing.append({"id": herb_id, "name": row.get("name"), "reason": "无 image_path"})
            continue

        src = HERB_SRC / str(rel).replace("\\", "/")
        if not src.exists():
            missing.append({"id": herb_id, "name": row.get("name"), "reason": f"文件不存在 {rel}"})
            continue

        dst = HERB_OUT / f"{herb_id}.webp"
        if dst.exists() and not force:
            skipped += 1
            total_bytes += dst.stat().st_size
            continue

        try:
            image = _open_rgb(src)
            image.thumbnail((COVER_SIZE, COVER_SIZE), Image.LANCZOS)
            image.save(dst, "WEBP", quality=WEBP_QUALITY, method=4)
            built += 1
            total_bytes += dst.stat().st_size
        except Exception as exc:  # noqa: BLE001
            failed.append({"id": herb_id, "name": row.get("name"), "error": str(exc)})

    return {
        "herbs": {
            "total": len(rows),
            "built": built,
            "skipped": skipped,
            "missing": missing,
            "failed": failed,
            "output_bytes": total_bytes,
        }
    }


def build_gallery_thumbs(force: bool = False) -> dict:
    """给每味药的所有图片生成 200px 小图，供放大层底部的缩略条使用。

    原图单张最大 1.6MB，一个图库条带若直接加载原图，一味药 13 张就是 20MB+，
    所以缩略条用小图、点开才加载原图。
    """
    GALLERY_OUT.mkdir(parents=True, exist_ok=True)
    with GraphClient() as client:
        rows = client.read(
            "MATCH (h:Herb) RETURN h.id AS id, h.image_path AS path", limit=2000
        )

    built, skipped, failed = 0, 0, []
    total_bytes = 0

    for row in rows:
        herb_id = str(row.get("id") or "")
        rel = row.get("path")
        if not herb_id or not rel:
            continue
        folder = HERB_SRC / str(rel).replace("\\", "/")
        folder = folder.parent
        if not folder.is_dir():
            continue

        files = sorted(
            [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS],
            key=lambda p: (int(p.stem.rsplit("_", 1)[-1]) if p.stem.rsplit("_", 1)[-1].isdigit() else 0, p.name),
        )
        for idx, src in enumerate(files):
            dst = GALLERY_OUT / f"{herb_id}_{idx}.webp"
            if dst.exists() and not force:
                skipped += 1
                total_bytes += dst.stat().st_size
                continue
            try:
                image = _open_rgb(src)
                image.thumbnail((GALLERY_SIZE, GALLERY_SIZE), Image.LANCZOS)
                image.save(dst, "WEBP", quality=GALLERY_QUALITY, method=4)
                built += 1
                total_bytes += dst.stat().st_size
            except Exception as exc:  # noqa: BLE001
                failed.append({"file": str(src), "error": str(exc)})

    return {
        "built": built,
        "skipped": skipped,
        "failed": failed,
        "output_bytes": total_bytes,
        "size": GALLERY_SIZE,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    started = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stats = build_herb_covers(force=args.force)
    stats["gallery"] = build_gallery_thumbs(force=args.force)

    stats["molecules"] = {
        "source_dir": str(MOL_SRC),
        "served_directly": True,
        "note": "分子结构图体积小（2~14KB），不做转换，由静态目录直发原图",
    }
    stats["built_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    manifest = OUT_DIR / "manifest.json"
    manifest.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    herb = stats["herbs"]
    gal = stats["gallery"]
    print(f"中药封面: 新建 {herb['built']}, 跳过 {herb['skipped']}, "
          f"缺失 {len(herb['missing'])}, 失败 {len(herb['failed'])}")
    print(f"封面总大小: {herb['output_bytes'] / 1024 / 1024:.1f} MB "
          f"（原图 1131.6 MB，压缩到 {herb['output_bytes'] / 1024 / 1024 / 1131.6:.1%}）")
    print(f"图库缩略: 新建 {gal['built']}, 跳过 {gal['skipped']}, 失败 {len(gal['failed'])}，"
          f"{gal['output_bytes'] / 1024 / 1024:.1f} MB")
    print(f"耗时 {time.perf_counter() - started:.1f}s → {HERB_OUT}")
    print(f"清单 → {manifest}")


if __name__ == "__main__":
    main()
