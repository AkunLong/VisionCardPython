# 获取榜单的mcp
# app/infra/ai/tikhub.py

# infra/ai/tikhub.py
from typing import List, Dict
import httpx


class TikHubTools:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://mcp.tikhub.io"
        self.headers = {"Authorization": f"Bearer {self.api_key}","Content-Type": "application/json",}

    async def list_tools(self) -> List[Dict]:
        """
        只负责：获取 TikHub 的 tools 定义
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.base_url}/tools", headers=self.headers)
            resp.raise_for_status()
            return resp.json()