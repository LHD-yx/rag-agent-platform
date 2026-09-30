"""查询改写：词典归一化 + HyDE 假设文档。

词典归一化（零成本）：把口语化说法、产品别名替换成文档里的标准写法；
HyDE（有成本）：让 LLM 先写一段"假设的标准答案"，用它的向量去检索，
对口语化、短查询的提升明显，代价是多一次 LLM 调用（约 +300ms）。

用法：python -m rag_agent.rewrite "扫描全能王咋装"
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .config import load_config, resolve

HYDE_PROMPT = """请针对下面的问题，写一段 150 字左右的"假设性文档片段"。
要求：使用专业技术文档的语气，包含可能的术语、型号和参数，但不必保证内容完全准确。
只输出这段文字，不要任何解释。

问题：{question}"""


def load_aliases(cfg: dict) -> dict[str, str]:
    """读取别名词典（configs/aliases.yaml），键按长度降序便于先替换长词。"""
    path: Path = resolve(cfg, "paths.alias_file")
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return dict(sorted(raw.items(), key=lambda kv: len(str(kv[0])), reverse=True))


class QueryRewriter:
    def __init__(self, cfg: dict | None = None, llm=None):
        self.cfg = cfg or load_config()
        self.aliases = load_aliases(self.cfg)
        self.llm = llm
        rc = self.cfg.get("rewrite", {})
        self.enable_alias = rc.get("enable_alias", True)
        self.enable_hyde = rc.get("enable_hyde", False)

    def normalize(self, query: str) -> str:
        """词典替换：别名/口语 -> 文档标准写法。"""
        if not self.enable_alias:
            return query
        text = query
        lowered = text.lower()
        for key, value in self.aliases.items():
            key_lower = str(key).lower()
            # 用 lower 匹配定位，保持原文其余部分不变
            if key_lower in lowered:
                idx = lowered.find(key_lower)
                text = text[:idx] + str(value) + text[idx + len(key_lower):]
                lowered = text.lower()
        return text

    def hyde(self, query: str) -> str | None:
        """生成假设文档；未配置 LLM 或未开启时返回 None。"""
        if not self.enable_hyde or self.llm is None:
            return None
        return self.llm.chat([{"role": "user", "content": HYDE_PROMPT.format(question=query)}])

    def expand(self, query: str) -> list[str]:
        """返回用于检索的查询列表：归一化后的原句（+ HyDE 假设文档）。"""
        queries = [self.normalize(query)]
        hypothetical = self.hyde(query)
        if hypothetical:
            queries.append(hypothetical)
        return queries


if __name__ == "__main__":
    import sys

    question = sys.argv[1] if len(sys.argv) > 1 else "扫描全能王咋装"
    rewriter = QueryRewriter()
    print("原始:", question)
    print("归一化后:", rewriter.normalize(question))
