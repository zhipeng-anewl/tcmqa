# -*- coding: utf-8 -*-
"""图片资源接口。

图谱里两类实体带图：
- 中药：`image_path` → `herb_images\\矮地茶\\HER0001_1.jpg`，一味药平均 5.7 张、最多 58 张；
- 化学成分：`structure_image_path` → `molecular_structures/MOL000001.png`，每成分一张结构式。

设计上的三个考虑：

1. **尺寸分流**：中药原图平均 200KB（共 1.13GB），给前端的是预生成的 480px webp 封面
   （共 18.7MB）；分子结构图只有 2~14KB，直接发原图，重编码反而更大。
2. **安全**：对外只暴露 `{herb_id}.webp` 这种由服务端拼出来的固定路径，
   多图浏览走「序号」而不是文件名，用户无法传入任意路径（杜绝目录穿越）。
3. **可配置**：原始图片目录不在仓库里，路径随机器不同，通过 settings 覆盖。

注意：原始图片目录缺失时接口要降级为「无图」，不能让整个服务起不来。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from tcmqa.api.deps import get_services

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/media", tags=["media"])

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _herb_dir(settings) -> Path:
    return Path(settings.herb_image_root) / "herb_images"


def _mol_dir(settings) -> Path:
    return Path(settings.mol_image_root)


def _cover_path(settings, herb_id: str) -> Path:
    return Path(settings.media_dir) / "herb" / f"{herb_id}.webp"


def _list_herb_images(settings, image_path: str | None) -> list[Path]:
    """按图谱里的 image_path 定位该中药的图片文件夹。"""
    if not image_path:
        return []
    relative = Path(str(image_path).replace("\\", "/"))
    folder = Path(settings.herb_image_root) / relative.parent
    if not folder.is_dir():
        return []
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS]

    # 按文件名里的序号排序（HER0001_1, HER0001_2, ... ），保证展示顺序稳定
    def sort_key(p: Path) -> tuple[int, str]:
        stem = p.stem
        tail = stem.rsplit("_", 1)[-1]
        return (int(tail) if tail.isdigit() else 0, p.name)

    return sorted(files, key=sort_key)


# ---------------------------------------------------------------------- #
@router.get("/resolve")
def resolve(
    request: Request,
    names: str = Query(..., description="逗号分隔的实体名，中药用中文、成分用英文"),
) -> dict[str, Any]:
    """批量把实体名解析成图片地址。

    前端在收到答案后，把证据里出现的药名/成分名一次性丢过来，
    换取 `{name: {label, id, thumb, orig, gallery}}`，避免一张图一个请求。
    """
    services = get_services(request.app)
    settings = services.settings

    wanted = [x.strip() for x in names.split(",") if x.strip()][:60]
    if not wanted:
        return {"items": {}}

    result: dict[str, Any] = {}

    # 中药按中文名精确查
    herbs = services.graph.read(
        "MATCH (h:Herb) WHERE h.name IN $names "
        "RETURN h.name AS name, h.id AS id, h.image_path AS image_path",
        {"names": wanted},
    )
    for row in herbs:
        herb_id = str(row.get("id") or "")
        cover = _cover_path(settings, herb_id)
        images = _list_herb_images(settings, row.get("image_path"))
        result[str(row["name"])] = {
            "label": "Herb",
            "id": herb_id,
            "thumb": f"/media/covers/{herb_id}.webp" if cover.exists() else "",
            "gallery": len(images),
            "orig": "",
        }

    # 成分按英文名不区分大小写查
    lowered = [w.lower() for w in wanted if w not in result]
    if lowered:
        ingredients = services.graph.read(
            "MATCH (i:Ingredient) WHERE toLower(i.name) IN $names "
            "RETURN i.name AS name, i.id AS id, i.structure_image_path AS path",
            {"names": lowered},
        )
        for row in ingredients:
            path = row.get("path")
            filename = Path(str(path).replace("\\", "/")).name if path else ""
            result[str(row["name"])] = {
                "label": "Ingredient",
                "id": str(row.get("id") or ""),
                "thumb": f"/media/mol/{filename}" if filename else "",
                "gallery": 1 if filename else 0,
                "orig": f"/media/mol/{filename}" if filename else "",
            }

    return {"items": result, "missing": [w for w in wanted if w not in result]}


@router.get("/herb/{herb_id}/images")
def herb_gallery(herb_id: str, request: Request) -> dict[str, Any]:
    """某味中药的全部图片（按序号返回地址，不暴露文件名）。"""
    services = get_services(request.app)
    settings = services.settings

    row = services.graph.read_one(
        "MATCH (h:Herb {id: $id}) RETURN h.name AS name, h.image_path AS image_path",
        {"id": herb_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"未找到中药：{herb_id}")

    images = _list_herb_images(settings, row.get("image_path"))
    gallery_dir = Path(settings.media_dir) / "herb_gallery"
    return {
        "id": herb_id,
        "name": row.get("name"),
        "count": len(images),
        "images": [
            {
                "index": idx,
                "url": f"/api/media/herb/{herb_id}/image/{idx}",
                # 缩略条用小图（约 8KB），点开才加载原图（单张最大 1.6MB）
                # 个别源图损坏会缺缩略图，这里如实返回空串，前端跳过
                "thumb": f"/media/gallery/{herb_id}_{idx}.webp"
                if (gallery_dir / f"{herb_id}_{idx}.webp").exists()
                else "",
                "filename": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
            }
            for idx, f in enumerate(images)
        ],
    }


@router.get("/herb/{herb_id}/image/{index}")
def herb_image(herb_id: str, index: int, request: Request) -> FileResponse:
    """大图。索引由服务端解析，客户端无法指定任意路径。"""
    services = get_services(request.app)
    settings = services.settings

    row = services.graph.read_one(
        "MATCH (h:Herb {id: $id}) RETURN h.image_path AS image_path", {"id": herb_id}
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"未找到中药：{herb_id}")

    images = _list_herb_images(settings, row.get("image_path"))
    if not images:
        raise HTTPException(status_code=404, detail="该中药暂无图片")
    if not 0 <= index < len(images):
        raise HTTPException(status_code=404, detail=f"图片序号越界（共 {len(images)} 张）")

    path = images[index]
    return FileResponse(path, media_type=_guess_media_type(path), headers={"Cache-Control": "public, max-age=86400"})


@router.get("/mol/{ingredient_id}")
def molecule_image(ingredient_id: str, request: Request) -> FileResponse:
    """分子结构式。按 ID 拼路径，不接受文件名参数。"""
    services = get_services(request.app)
    settings = services.settings

    row = services.graph.read_one(
        "MATCH (i:Ingredient {id: $id}) RETURN i.name AS name, "
        "i.structure_image_path AS path",
        {"id": ingredient_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"未找到成分：{ingredient_id}")

    path = row.get("path")
    if not path:
        raise HTTPException(status_code=404, detail="该成分暂无结构图")

    file = _mol_dir(settings) / Path(str(path).replace("\\", "/")).name
    if not file.is_file():
        raise HTTPException(status_code=404, detail="结构图文件缺失")
    return FileResponse(file, media_type=_guess_media_type(file), headers={"Cache-Control": "public, max-age=86400"})


@router.get("/stats")
def stats(request: Request) -> dict[str, Any]:
    """图片资源就绪情况，用于健康检查与答辩时说明。"""
    services = get_services(request.app)
    settings = services.settings

    herb_source = _herb_dir(settings)
    mol_source = _mol_dir(settings)
    covers = Path(settings.media_dir) / "herb"

    return {
        "herb_source": {
            "path": str(herb_source),
            "exists": herb_source.is_dir(),
            "herbs": len([d for d in herb_source.iterdir() if d.is_dir()])
            if herb_source.is_dir() else 0,
        },
        "mol_source": {
            "path": str(mol_source),
            "exists": mol_source.is_dir(),
            "files": len([f for f in mol_source.iterdir() if f.is_file()])
            if mol_source.is_dir() else 0,
        },
        "covers": {
            "path": str(covers),
            "count": len(list(covers.glob("*.webp"))) if covers.is_dir() else 0,
        },
    }


def _guess_media_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "application/octet-stream")
