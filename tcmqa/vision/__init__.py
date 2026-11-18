# -*- coding: utf-8 -*-
"""多模态检索层（Chinese-CLIP）。"""
from tcmqa.vision.encoder import ClipEncoder
from tcmqa.vision.index import ImageEntry, VisionHit, VisionIndex
from tcmqa.vision.retriever import VisionRetriever

__all__ = ["ClipEncoder", "VisionIndex", "VisionHit", "ImageEntry", "VisionRetriever"]
