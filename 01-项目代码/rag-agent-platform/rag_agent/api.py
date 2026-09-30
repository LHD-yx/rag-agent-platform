"""FastAPI 服务：同步接口 + SSE 流式接口 + 健康检查。

启动：python main.py serve      或      uvicorn rag_agent.api:app --reload
"""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .pipeline import RagPipeline
from .generate import source_label

app = FastAPI(title="企业知识库问答服务", version="0.2.0")

MAX_CONCURRENCY = 8  # 单机并发上限，避免打爆 embedding / LLM 配额
_limiter = asyncio.Semaphore(MAX_CONCURRENCY)
_pipeline: RagPipeline | None = None


def get_pipeline() -> RagPipeline:
    """懒加载：首次请求时才加载索引与模型配置。"""
    global _pipeline
    if _pipeline is None:
        _pipeline = RagPipeline()
    return _pipeline


class QueryRequest(BaseModel):
    question: str
    use_cache: bool = True


@app.get("/health")
async def health() -> dict:
    pipeline = get_pipeline()
    return {
        "status": "ok",
        "chunks": len(pipeline.retriever.chunks),
        "cache": pipeline.cache.stats(),
    }


@app.post("/query")
async def query(req: QueryRequest) -> dict:
    async with _limiter:
        pipeline = get_pipeline()
        result = await run_in_threadpool(pipeline.answer, req.question, req.use_cache)
    return {
        "answer": result["answer"],
        "refused": result["refused"],
        "citations": result["citations"],
        "invalid_citations": result["invalid_citations"],
        "cached": result.get("cached", False),
        "queries": result["queries"],
        "timings_ms": {k: round(v) for k, v in result["timings"].items()},
        "contexts": [
            {
                "index": i,
                "title": c.get("title", ""),
                "source": source_label(c),
                "score": round(c.get("score", 0.0), 4),
                "snippet": c["text"][:120],
            }
            for i, c in enumerate(result["contexts"], start=1)
        ],
    }


@app.post("/query/stream")
async def query_stream(req: QueryRequest):
    """SSE 流式接口：先推检索到的上下文，再逐 token 推答案。"""

    async def event_generator():
        async with _limiter:
            pipeline = get_pipeline()
            for event in pipeline.stream(req.question):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
