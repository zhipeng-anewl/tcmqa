# -*- coding: utf-8 -*-
"""全局配置：优先读环境变量，其次读项目根目录 .env，最后用默认值。

用 pydantic-settings，好处是配置项有类型校验、集中在可枚举的类里，
新增配置只改一处，不会散落成 os.getenv() 满天飞。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
INDEX_DIR = DATA_DIR / "index"
CACHE_DIR = DATA_DIR / "cache"


class Settings(BaseSettings):
    """全部运行期配置。字段名小写，环境变量名自动大写匹配。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------- Neo4j ----------------
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"
    neo4j_query_timeout: float = 15.0
    neo4j_max_rows: int = 200

    # ---------------- LLM ----------------
    deepseek_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout: float = 120.0
    llm_max_retries: int = 3
    llm_max_concurrency: int = 4

    # ---------------- Embedding ----------------
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 32
    # bge 系列检索任务建议给查询加指令前缀，文档端不加
    embedding_query_prefix: str = "为这个句子生成表示以用于检索相关文章："
    hf_home: str = str(CACHE_DIR / "hf")
    hf_endpoint: str = "https://hf-mirror.com"

    # ---------------- 检索 ----------------
    vector_top_k: int = 8
    bm25_top_k: int = 8
    fuse_top_k: int = 6
    rrf_k: int = 60  # Reciprocal Rank Fusion 的平滑常数
    few_shot_top_k: int = 3

    # ---------------- Agent / 缓存 ----------------
    cypher_max_repair: int = 2
    cache_ttl_seconds: int = 3600
    semantic_cache_threshold: float = 0.95
    max_question_chars: int = 500

    # ---------------- 消融实验开关（仅评测用，生产保持 False） ----------------
    # 关掉某个模块再跑同一套金标集，用通过率差值衡量该模块的贡献
    ablate_vector: bool = False     # 关掉向量检索分支
    ablate_aliases: bool = False    # 关掉 LLM 给出的英文别名（只靠中文原词链接）
    ablate_repair: bool = False     # 关掉 Cypher 自修复闭环
    ablate_weak_prompt: bool = False  # 弱化提示词（去少样本、去 DISTINCT 提示）

    # ---------------- 服务 ----------------
    app_name: str = "中医药知识图谱智能问答系统"
    log_level: str = "INFO"
    cors_origins: str = "*"
    sqlite_path: str = str(DATA_DIR / "app.db")

    # ---------------- 公网部署：限流与配额 ----------------
    # 本地开发保持 0（不限流）；公网上线建议 6 / 800，见 docs/deploy.md
    rate_limit_per_minute: int = 0
    daily_chat_limit: int = 0
    # 反向代理（Caddy / Nginx）后面才置 True，否则 X-Forwarded-For 可被伪造
    trust_proxy_headers: bool = False

    # ---------------- 图片资源 ----------------
    # 原始图片不在仓库内，路径随机器不同，只能用环境变量指定。
    # 默认空串：没配就不提供大图/分子结构图（封面与缩略图在 data/images 里，不受影响）。
    #   HERB_IMAGE_ROOT=D:\path\to\构建知识图谱
    #   MOL_IMAGE_ROOT=D:\path\to\构建知识图谱\TCMSP\molecular_structures
    herb_image_root: str = ""
    mol_image_root: str = ""
    media_dir: str = str(DATA_DIR / "images")

    # ---------------- 多模态图像检索 ----------------
    clip_model: str = "OFA-Sys/chinese-clip-vit-base-patch16"
    vision_index_dir: str = str(INDEX_DIR / "vision")
    vision_top_k: int = 8
    vision_max_upload_mb: int = 8
    # 文本查询时「实体文本先验」与「图像相似度」的融合权重。
    # 0.5 是 alpha 扫描出来的最优点（见 docs/multimodal.md）：纯跨模态 Top-5 仅 40%，
    # 纯文本 78.7%，融合后 86.0%。
    vision_text_alpha: float = 0.5

    # ---------------- 计费估算（元 / 百万 token，按 DeepSeek 官方价粗估） ----------------
    price_input_cache_hit: float = 0.5
    price_input_cache_miss: float = 2.0
    price_output: float = 8.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    def prepare_dirs(self) -> None:
        for d in (DATA_DIR, INDEX_DIR, CACHE_DIR):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.prepare_dirs()
    return s
