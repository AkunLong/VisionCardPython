# mcp的协议客户端
# app/infra/mcp/client.py

import httpx
import json
import uuid
import logging
from typing import Any, Dict, List


logger = logging.getLogger(__name__)


class MCPClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 60.0,
    ):
        self.base_url = base_url
        self.api_key = api_key.strip()
        self.timeout = httpx.Timeout(timeout, connect=10.0)

    async def call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        统一 MCP 调用入口（支持 SSE / JSON）
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        payload = {
            "jsonrpc": "2.0",
            "id": f"mcp-{uuid.uuid4().hex}",
            "method": method,
            "params": params,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.base_url,
                headers=headers,
                json=payload,
            )

            if resp.status_code != 200:
                raise RuntimeError(f"MCP error {resp.status_code}: {resp.text}")

            return self._parse_response(resp.text)

    def _parse_response(self, raw_text: str) -> Dict[str, Any]:
        """
        合并 SSE data，返回最终 JSON
        """
        data_chunks: List[str] = []

        for line in raw_text.splitlines():
            if line.startswith("data:"):
                content = line[5:].strip()
                if content and content != "[DONE]":
                    data_chunks.append(content)

        # 多段时，取最后一段（当前智谱语义）
        final_json = data_chunks[-1] if data_chunks else raw_text
        return json.loads(final_json)