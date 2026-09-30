"""文档解析、清洗与切片。

切片策略：先按标题层级切章节，章节超长再滑动切分，
每个片段携带「标题路径」前缀用于向量化——这是提升召回的关键细节。

用法：python -m rag_agent.chunking
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterator

from .config import load_config, resolve

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
PAGE_NUMBER_RE = re.compile(r"^\s*[-—]?\s*\d{1,3}\s*[-—]?\s*$", re.M)
SUPPORTED = {".pdf", ".docx", ".doc", ".md", ".markdown", ".txt"}


def read_text(path: Path) -> str:
    """按扩展名解析成带 Markdown 标题标记的纯文本。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import fitz  # PyMuPDF

        doc = fitz.open(path)
        return "\n".join(page.get_text() for page in doc)
    if suffix in {".docx", ".doc"}:
        from docx import Document

        document = Document(path)
        lines: list[str] = []
        for para in document.paragraphs:
            style = (para.style.name or "").lower()
            if style.startswith("heading"):
                level = int("".join(ch for ch in style if ch.isdigit()) or 1)
                lines.append("#" * min(level, 6) + " " + para.text)
            else:
                lines.append(para.text)
        return "\n".join(lines)
    return path.read_text(encoding="utf-8", errors="ignore")


def clean_text(text: str) -> str:
    """统一空白、去页码/页眉类噪声行。"""
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = PAGE_NUMBER_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def content_hash(text: str) -> str:
    """用于文档级近似去重。"""
    normalized = re.sub(r"\s+", "", text)
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def split_sections(text: str) -> list[tuple[str, str]]:
    """按 Markdown 标题切成 (标题路径, 正文)。"""
    sections: list[tuple[str, str]] = []
    stack: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append((" > ".join(stack), body))
        buffer.clear()

    for line in text.splitlines():
        match = HEADING_RE.match(line.strip())
        if match:
            flush()
            level = len(match.group(1))
            stack = stack[: level - 1]
            stack.append(match.group(2).strip())
        else:
            buffer.append(line)
    flush()

    if not sections:
        sections = [("", text)]
    return sections


def sliding_window(text: str, max_chars: int, overlap: int) -> Iterator[str]:
    """按字符滑窗切分，保证相邻片段有重叠。"""
    text = text.strip()
    if not text:
        return
    if len(text) <= max_chars:
        yield text
        return
    start = 0
    while start < len(text):
        yield text[start:start + max_chars]
        if start + max_chars >= len(text):
            break
        start += max_chars - overlap


def chunk_document(doc_id: str, title: str, text: str, cfg: dict,
                   source_type: str = "") -> list[dict]:
    cc = cfg["chunking"]
    chunks: list[dict] = []
    for s_idx, (section_path, body) in enumerate(split_sections(text)):
        for c_idx, piece in enumerate(
            sliding_window(body, cc["max_chars"], cc["overlap"])
        ):
            piece = piece.strip()
            if len(piece) < cc["min_chars"]:
                continue
            # section_path 已包含顶级标题（通常是文档名），避免重复拼接
            prefix = section_path or title
            chunks.append(
                {
                    "chunk_id": f"{doc_id}-{s_idx}-{c_idx}",
                    "doc_id": doc_id,
                    "title": title,
                    "section_path": section_path,
                    "source_type": source_type,
                    "text": piece,
                    # embed_text 带标题上下文，用于向量化；text 用于 BM25 与展示
                    "embed_text": f"{prefix}\n{piece}" if prefix else piece,
                }
            )
    return chunks


def build_chunks(cfg: dict | None = None) -> list[dict]:
    """扫描 data/raw，解析、去重、切片。"""
    cfg = cfg or load_config()
    raw_dir = resolve(cfg, "paths.raw_dir")
    out_path = resolve(cfg, "paths.chunks_file")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    files = [p for p in sorted(raw_dir.rglob("*")) if p.suffix.lower() in SUPPORTED]
    seen_hashes: set[str] = set()
    all_chunks: list[dict] = []
    stats = {"files": 0, "skipped_dup": 0, "docs": 0, "chunks": 0}

    for path in files:
        stats["files"] += 1
        text = clean_text(read_text(path))
        if not text:
            continue
        signature = content_hash(text)
        if signature in seen_hashes:
            stats["skipped_dup"] += 1
            continue
        seen_hashes.add(signature)
        stats["docs"] += 1
        # doc_id 用"相对 data/raw 的路径"来算，而不是绝对路径。
        # 原因：用绝对路径的话，项目换目录（或别人把仓库克隆到别的路径）之后，
        # 所有 doc_id 都会变，随仓库提交的评测集里 gold id 会全部失效、评测直接归零。
        # 改成相对路径后，同一份语料在任何位置、任何机器上算出来的 id 都一致。
        rel_path = path.relative_to(raw_dir).as_posix()
        doc_id = content_hash(rel_path)[:10]
        chunks = chunk_document(
            doc_id=doc_id,
            title=path.stem,
            text=text,
            cfg=cfg,
            source_type=path.suffix.lower().lstrip("."),
        )
        all_chunks.extend(chunks)
        stats["chunks"] += len(chunks)

    with open(out_path, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    # 分格式统计：同样的内容，Markdown 有标题层级可以切得更细，
    # PDF 抽不出标题层级、只能按长度硬切，片段明显偏粗。
    # 这个对比是"为什么要基于标题层级切片"的直接证据。
    by_type: dict[str, list[dict]] = {}
    for chunk in all_chunks:
        by_type.setdefault(chunk.get("source_type", "unknown"), []).append(chunk)
    type_rows = []
    for ext, items in by_type.items():
        docs = len({c["doc_id"] for c in items})
        type_rows.append((ext, docs, len(items), len(items) / max(docs, 1)))
    type_rows.sort(key=lambda r: -r[2])
    breakdown = "\n".join(
        f"  - {ext}: {docs} 篇 / {count} 片段（{per:.1f} 片/篇）"
        for ext, docs, count, per in type_rows
    )

    report = (
        f"原始文件数: {stats['files']}\n"
        f"去重跳过: {stats['skipped_dup']}\n"
        f"有效文档数: {stats['docs']}\n"
        f"片段总数: {stats['chunks']}\n"
        f"平均每篇片段数: {stats['chunks'] / max(stats['docs'], 1):.1f}\n"
        f"\n分格式统计（篇数 / 片段数 / 片每篇）:\n{breakdown}\n"
    )
    report_path = out_path.parent / "chunk_report.txt"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"切片已写入: {out_path}")
    return all_chunks


if __name__ == "__main__":
    build_chunks()
