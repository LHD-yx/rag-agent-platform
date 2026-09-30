"""LLM 客户端封装（OpenAI 兼容接口）。

适配 SiliconFlow / DeepSeek / 阿里云百炼 / 智谱，以及本地 vLLM 的
OpenAI 兼容端口——只改 base_url 与 model 即可。
"""
from __future__ import annotations

import os
from typing import Iterator, Sequence


class LLMClient:
    def __init__(self, model: str, base_url: str, api_key_env: str,
                 temperature: float = 0.2, max_tokens: int = 1024):
        from openai import OpenAI

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"未找到环境变量 {api_key_env}，请在 .env 中配置")
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def chat(self, messages: Sequence[dict], **kwargs) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            temperature=kwargs.pop("temperature", self.temperature),
            max_tokens=kwargs.pop("max_tokens", self.max_tokens),
            **kwargs,
        )
        return resp.choices[0].message.content or ""

    def stream(self, messages: Sequence[dict], **kwargs) -> Iterator[str]:
        """逐 token 产出，供 SSE 流式接口使用。"""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            temperature=kwargs.pop("temperature", self.temperature),
            max_tokens=kwargs.pop("max_tokens", self.max_tokens),
            stream=True,
            **kwargs,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


def build_llm(cfg: dict) -> LLMClient:
    lc = cfg["llm"]
    return LLMClient(
        model=lc["model"],
        base_url=lc["base_url"],
        api_key_env=lc["api_key_env"],
        temperature=lc.get("temperature", 0.2),
        max_tokens=lc.get("max_tokens", 1024),
    )
