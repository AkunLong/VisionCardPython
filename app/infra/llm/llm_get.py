# LLM模型接口调用
# app/infra/llm/llm_get.py

import logging
import json
import httpx
from typing import AsyncGenerator, List, Dict, Any, Optional
# 导入全局并发控制信号量
from app.infra.concurrency import LLM_SEMAPHORE

logger = logging.getLogger(__name__)


class LLMProvider:
    def __init__(self, api_key: str, base_url: str, model: str = "deepseek-chat"):
        """
        初始化 DeepSeek 提供者
        :param api_key: 你的 DeepSeek API Key
        :param base_url: API 基础地址 (例如: https://api.deepseek.com)
        :param model: 模型名称，默认使用 deepseek-chat (V3)
        """
        self.api_key = api_key
        # 统一处理 URL 结尾，避免拼接时出现双斜杠
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat_completion(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
            tool_choice: str = "auto"
    ) -> Dict[str, Any]:
        """
        非流式对话接口：支持常规对话、多轮对话历史、以及工具调用 (Tool Calling)
        """

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            # 【设置 1】最大输出长度
            # deepseek-chat 默认约 4K，手动设为 8K (8192) 以应对长网页代码
            "max_tokens": 8192
        }

        # 【设置 2】细化超时控制
        # 流式传输建议关闭 read timeout，防止 AI 思考过久或传输长文本时断连
        timeout_settings = httpx.Timeout(
            connect=10.0,  # 连接超时
            read=None,  # 读取超时设为 None (关键：防止长流中断)
            write=10.0,  # 写入超时
            pool=10.0  # 连接池超时
        )

        # 如果传入了工具定义，则加入请求参数
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        # 使用信号量控制并发：只有获取到信号量后才能发起网络请求
        async with LLM_SEMAPHORE:
            logger.info(f"[llm=deepseek chat_completion start")
            async with httpx.AsyncClient(timeout=timeout_settings) as client:
                try:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self.headers,
                        json=payload,
                    )
                    # 检查 HTTP 状态码
                    resp.raise_for_status()
                    logger.info(f"[llm=deepseek success")
                    return resp.json()
                except Exception as e:
                    logger.error(f"[llm=deepseek error: {str(e)}")
                    raise

    async def chat_completion_stream(
            self,
            messages: List[Dict[str, Any]]
    ) -> AsyncGenerator[str, None]:
        """
        流式对话接口：实时返回模型生成的文本片段
        注意：流式模式通常用于纯文本交互，工具调用一般建议使用非流式接口
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            # 【设置 1】最大输出长度
            # deepseek-chat 默认约 4K，手动设为 8K (8192) 以应对长网页代码
            "max_tokens": 8192
        }

        # 【设置 2】细化超时控制
        # 流式传输建议关闭 read timeout，防止 AI 思考过久或传输长文本时断连
        timeout_settings = httpx.Timeout(
            connect=10.0,  # 连接超时
            read=None,  # 读取超时设为 None (关键：防止长流中断)
            write=10.0,  # 写入超时
            pool=10.0  # 连接池超时
        )
        # 并发控制：流式请求也会占用一个并发槽位，直到流结束
        async with LLM_SEMAPHORE:
            logger.info(f"[llm=deepseek stream start")
            async with httpx.AsyncClient(timeout=timeout_settings) as client:
                async with client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        headers=self.headers,
                        json=payload,
                ) as response:
                    response.raise_for_status()

                    # 迭代处理 SSE (Server-Sent Events) 响应流
                    async for line in response.aiter_lines():
                        # 过滤掉非数据行（DeepSeek 会返回 data: 开头的行）
                        if not line.startswith("data: "):
                            continue

                        # 移除前缀获取 JSON 字符串
                        json_str = line[6:]

                        # 检查流是否结束
                        if json_str.strip() == "[DONE]":
                            break

                        try:
                            chunk = json.loads(json_str)
                            # 提取增量内容 delta.content
                            delta = chunk["choices"][0].get("delta", {})
                            if content := delta.get("content"):
                                yield content
                        except Exception as e:
                            logger.error(f"解析流片段失败: {e}, 原文: {line}")