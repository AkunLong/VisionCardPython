# 获取搜索的mcp
# app/infra/ai/glm.py

from typing import List, Dict, Any
from app.infra.mcp.client import MCPClient
import httpx
import logging
logger = logging.getLogger(__name__)


class GLMTools:
    def __init__(self, base_url: str, api_key: str):
        self.api_key = api_key
        self.client = MCPClient(base_url=base_url, api_key=api_key)

    async def list_tools(self) -> List[Dict]:
        """
        只负责：调用 GLM MCP 的 tools/list
        不做 tools/call
        不做搜索
        """
        resp = await self.client.call("tools/list", {})
        return resp.get("result", {}).get("tools", [])

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        fallback_query: str | None = None,
    ) -> Dict:
        """
        🔥 核心：把 MCP tool → Web Search API
        """
        WEB_SEARCH_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"
        TOOL_ENGINE_MAP = {
            "webSearchStd": "search_std",
            "webSearchPro": "search_pro",
            "webSearchSogou": "search_pro_sogou",
            "webSearchQuark": "search_pro_quark",
        }

        if tool_name not in TOOL_ENGINE_MAP:
            raise ValueError(f"未知的 GLM 搜索工具: {tool_name}")

        search_engine = TOOL_ENGINE_MAP[tool_name]

        search_query = arguments.get("search_query") or fallback_query
        if not search_query:
            raise ValueError("search_query 不能为空")
        logger.info(f"search_query: {search_query}")
        payload = {
            "search_query": search_query,
            "search_engine": search_engine,
            "count": arguments.get("count", 10),
            "search_recency_filter": arguments.get("search_recency_filter", "noLimit"),
            "content_size": arguments.get("content_size", "medium"),
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                WEB_SEARCH_URL,
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()