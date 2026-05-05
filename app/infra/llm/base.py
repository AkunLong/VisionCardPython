# llm的统一接口管理
# app/infra/llm/base.py

from typing import Protocol


class LLMProvider(Protocol):
    async def generate_text(self, *, prompt: str, job_id: str) -> str:
        ...
