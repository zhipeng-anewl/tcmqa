# -*- coding: utf-8 -*-
"""中医药知识图谱智能问答系统。

分层：
    tcmqa.llm     —— 大模型客户端与版本化 Prompt
    tcmqa.kg      —— 图数据库访问、Schema、Cypher 只读守卫、实体链接
    tcmqa.rag     —— 语料构建、向量/BM25 检索、GraphRAG 编排
    tcmqa.store   —— SQLite 持久化（会话、轨迹、反馈、缓存、评测）
    tcmqa.api     —— FastAPI 路由
    tcmqa.eval    —— 金标集评测
"""

__version__ = "2.0.0"
