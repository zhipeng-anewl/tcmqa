# -*- coding: utf-8 -*-
"""图谱 Schema 描述。

Schema 说明是 Text2Cypher 效果的命门：模型不知道标签和属性，就一定瞎编。
这里维护一份「给人看也给模型看」的说明，并额外提供带实时统计的版本，
让模型知道数据量级（例如 TREATS 有 12 万条边 → 必须 DISTINCT，否则结果爆炸）。
"""

from __future__ import annotations

from typing import Any

SCHEMA_TEXT = """
### 节点（标签 : 中文名）
- `(:Herb)` 中药。属性：`id`(如 HER0001)、`name`(中文药名)、`effect`(功效分类，如"补气药""清热解毒药")、`image_path`
- `(:Ingredient)` 化学成分。属性：`id`(如 MOL000001)、`name`(**英文名**)、`molecular_weight`、`logP`、`H_bond_donors`、`H_bond_acceptors`、`rotatable_bonds`、`topological_polar_SA`、`fractional_accessible_SA`、`inchikey`
- `(:Target)` 靶点蛋白。属性：`id`、`name`(**英文名**)
- `(:Disease)` 疾病。属性：`id`、`name`(**英文名**)、`icd9`、`icd10`
- `(:IngredientADME)` 成分药代参数。属性：`ingredient_id`、`oral_bioavailability`(0~1)、`drug_likeness`、`caco2_permeability`、`blood_brain_barrier`、`half_life`(多为空)

### 关系（全部有向）
- `(:Herb)-[:CONTAINS]->(:Ingredient)`        中药含有该成分
- `(:Herb)-[:TREATS]->(:Disease)`             中药可治疗该疾病（**边非常密集**）
- `(:Ingredient)-[:TARGETS]->(:Target)`       成分作用于该靶点
- `(:Ingredient)-[:INDICATED_FOR]->(:Disease)` 成分可用于该疾病（**边非常多**）
- `(:Target)-[:INVOLVED_IN]->(:Disease)`      靶点参与该疾病
- `(:Ingredient)-[:HAS_ADME]->(:IngredientADME)` 成分的药代参数

### 注意事项
- 中药名是**中文**，成分/靶点/疾病名是**英文**，跨语言匹配要靠上层实体链接，Cypher 里不要自己翻译。
- `TREATS` 平均每味药 250+ 条边，直接查会返回大量重复中药，**必须 DISTINCT**。
- `half_life` 大量为空，查询时用 OPTIONAL MATCH。
"""


def build_schema_text(stats: dict[str, Any] | None = None, minimal: bool = False) -> str:
    """在基础 Schema 后附一段实时统计，让模型对数据规模有感知。

    minimal=True 时去掉「注意事项」——用于消融实验：故意不告诉模型
    「TREATS 边很密集、必须 DISTINCT」，看首次生成会不会更容易出错。
    """
    base = SCHEMA_TEXT.strip()
    if minimal:
        base = base.split("### 注意事项")[0].strip()

    if not stats:
        return base
    labels = stats.get("labels") or {}
    rels = stats.get("relationship_types") or {}
    if not labels and not rels:
        return base

    label_line = "、".join(f"{k}={v}" for k, v in labels.items())
    rel_line = "、".join(f"{k}={v}" for k, v in rels.items())
    return (
        base
        + "\n\n### 实时规模\n"
        + f"- 节点：{label_line}（共 {stats.get('nodes', 0)}）\n"
        + f"- 关系：{rel_line}（共 {stats.get('relationships', 0)}）"
    )
