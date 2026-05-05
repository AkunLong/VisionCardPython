# mcp的统一接口层
# app/infra/ai/api.py

from typing import List, Dict, Any
import httpx
from app.config import settings
from app.infra.mcp.glm import GLMTools
from app.infra.mcp.tikhub import TikHubTools
import json

class UnifiedToolsAPI:
    """
    Infra 层：
    - 持有 key / url
    - 提供 tools
    - 提供 tool 执行
    """

    def __init__(self):
        self.glm = GLMTools(
            base_url=settings.GLM_MCP_BASE_URL,
            api_key=settings.GLM_API_KEY,
        )
        self.tikhub = TikHubTools(
            api_key=settings.TIKHUB_API_KEY,
        )

    # ---------- tools ----------

    async def list_glm_tools(self) -> List[Dict]:
        return await self.glm.list_tools()

    async def list_tikhub_tools(self) -> List[Dict]:
        return await self.tikhub.list_tools()

    # ---------- execution ----------

    async def call_tikhub_tool(
            self,
            tool_name: str,
            arguments: Dict[str, Any],
    ) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://mcp.tikhub.io/tools/call",
                headers={
                    "Authorization": f"Bearer {settings.TIKHUB_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
            )

            if resp.status_code != 200:
                return json.dumps({
                    "ok": False,
                    "tool": tool_name,
                    "platform": tool_name.split("_")[0],
                    "status_code": resp.status_code,
                    "recoverable": resp.status_code in (404, 429, 500, 502),
                    "error": "TikHub 接口调用失败",
                    "detail": resp.text[:1000],
                    "suggestion": "请尝试同平台的其他接口或更高版本接口"
                }, ensure_ascii=False)

            return json.dumps({
                "ok": True,
                "tool": tool_name,
                "data": resp.json()
            }, ensure_ascii=False)



    async def call_glm_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        fallback_query: str | None = None,
    ) -> Dict:
        """
        执行 GLM MCP 搜索工具

        - DeepSeek 可能不传 search_query
        - fallback_query 用 user_prompt 兜底
        """

        # ---------- 1️⃣ 参数兜底 ----------
        if not arguments or not arguments.get("search_query"):
            if not fallback_query:
                raise ValueError(
                    f"GLM tool `{tool_name}` missing search_query and no fallback_query provided"
                )
            arguments = dict(arguments or {})
            arguments["search_query"] = fallback_query

        # ---------- 2️⃣ 正确调用（⚠️ 用位置参数） ----------
        return await self.glm.call_tool(
            tool_name,      # ← 位置参数
            arguments,      # ← 位置参数
        )

    def to_openai_tools(self,raw_tools):
        mcp_tools = [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            }
        } for t in raw_tools]
        return mcp_tools

# 对外只暴露 infra 实例
api = UnifiedToolsAPI()
#import asyncio
#text = asyncio.run(api.list_glm_tools())
#print(text)