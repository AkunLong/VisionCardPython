# 整合功能后的完整Agent
# app/infra/mcp/agent.py

import json
from typing import Dict, Any, List

from openai import AsyncOpenAI
from app.config import settings
from app.infra.mcp.api import api as mcp_api
import datetime
import asyncio  # 必须导入
from openai import APITimeoutError # 捕获超时异常

# 文件日志初始化
import logging
logger = logging.getLogger(__name__)

# 导入进度任务
from app.workers.job_events import emit
from app.domain.job_repo import JobEventType

# 导入提示词管理系统
from app.orchestrator.prompt_manager import prompt_manager
# 稳定性指南（喂给 DeepSeek）
STABILITY_GUIDE_CASE = prompt_manager.get_prompt(task="get_news", domain="finance", mode="am_gen")[0]

# ===============================
# MCP Agent Runner（测试用）
# ===============================
class MCPAgentRunner:
    MAX_TOOL_ROUNDS = 30

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )

    # ------------------------------------------------
    # Tool Router（⭐ 关键：fallback_query 在这里注入）
    # ------------------------------------------------
    async def dispatch_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        tikhub_tools: List[Dict],
        glm_tools: List[Dict],
        user_prompt: str,
    ) -> Dict:
        """
        根据 tool_name 自动路由到 TikHub / GLM
        """

        # ---- TikHub tools ----
        if any(t["name"] == tool_name for t in tikhub_tools):
            print(f"📡 路由 → TikHub MCP: {tool_name}")
            return await mcp_api.call_tikhub_tool(tool_name, tool_args)

        # ---- GLM Web Search tools ----
        if any(t["name"] == tool_name for t in glm_tools):
            print(f"📡 路由 → GLM MCP: {tool_name}")

            # ⭐ 核心兜底逻辑
            return await mcp_api.call_glm_tool(
                tool_name=tool_name,
                arguments=tool_args,
                fallback_query=user_prompt,
            )

        # ---- Unknown ----
        return {
            "error": f"Unknown tool: {tool_name}",
            "tool_args": tool_args,
        }

    # ------------------------------------------------
    # Main Agent Loop
    # ------------------------------------------------
    async def run(
        self,
        system_prompt: str,
        user_prompt: str,
        job:dict = None,
    ) -> str:
        print("🔧 正在加载 MCP tools...")

        # 1️⃣ 加载 tools
        raw_tikhub_tools = await mcp_api.list_tikhub_tools()
        raw_glm_tools = await mcp_api.list_glm_tools()

        tikhub_tools = mcp_api.to_openai_tools(raw_tikhub_tools)
        glm_tools = mcp_api.to_openai_tools(raw_glm_tools)

        all_tools = tikhub_tools + glm_tools
        # 1. 自动生成代码层面的环境信息
        now_time = datetime.datetime.now()
        timestamp_str = now_time.strftime("%Y-%m-%d %H:%M")
        week_day = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now_time.weekday()]
        constraints = """
        [工具调用规范]
        1. 调用搜索工具时，search_query 参数必须是简洁的关键词（如 "Anthropic 新工具 美股影响"）。
        2. 严禁将任务指令、系统提示词或整个报告大纲作为搜索参数发送。
        3. 搜索词应尽可能精准，字数控制在 20 字以内。
        """
        messages:list = [
            {"role": "system", "content": f"{constraints}\n\n当前环境：{timestamp_str} ({week_day})\n\n;{STABILITY_GUIDE_CASE}\n\n;如果你需要调用工具，请最多尝试 20 次工具调用，20次后必须强制输出结果，避免死循环;\n\n{system_prompt}"},
            {
                "role": "user",
                "content": f"{user_prompt}",
            }
        ]

        round_count = 0

        while round_count < self.MAX_TOOL_ROUNDS:
            round_count += 1
            print(f"\n🔁 Round {round_count}")

            try:
                # ⭐ 核心修改：设置 180 秒（3分钟）强制超时
                # 如果 3 分钟不回，直接抛出 asyncio.TimeoutError
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model="deepseek-reasoner",
                        messages=messages,
                        tools=all_tools,
                        # 注意：此处的 timeout 是 httpx 层的，wait_for 是异步任务层的，双重保险
                        timeout=180.0
                    ),
                    timeout=185.0  # 比 API timeout 稍微大一点点
                )
            except (asyncio.TimeoutError, APITimeoutError):
                print(f"⚠️ Round {round_count} 响应超时（3分钟）")

                # 💡 补丁逻辑：如果最后一条消息有 tool_calls 但没有对应的 tool 回复，API 会炸
                last_msg = messages[-1] if messages else None
                if last_msg and getattr(last_msg, "role", None) == "assistant" and getattr(last_msg, "tool_calls",
                                                                                           None):
                    # 为每一个未完成的 tool_call 补一个“超时”回复
                    for tool_call in last_msg.tool_calls:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": "错误：工具调用响应超时，请尝试减小搜索范围或直接根据现有信息输出。"
                        })
                else:
                    # 如果不是因为等待工具回复超时，而是模型思考太久超时
                    messages.append({
                        "role": "user",
                        "content": "（系统提示：响应超时。如果你正在思考，请直接给出目前的结论或简要执行下一步。）"
                    })

                emit(job, "⏳ 响应过慢，尝试恢复中...", event_type=JobEventType.INFO)
                continue

            msg = response.choices[0].message
            messages.append(msg)

            # 🧠 reasoning（DeepSeek-R1 特有）
            if getattr(msg, "reasoning_content", None):
                print("\n🧠 thinking:\n", msg.reasoning_content)
                emit(job, f'🤖思考中：{msg.reasoning_content[:36]}...',event_type=JobEventType.INFO, progress=50)

            # 没有工具调用 → 结束
            if not msg.tool_calls:
                return msg.content

            # 执行工具调用
            for tool_call in msg.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments or "{}")

                print(f"🛠️ 执行工具: {tool_name}")
                # --- 新增：参数合法性检查 ---
                if "search_query" in tool_args and len(tool_args["search_query"]) > 100:
                    print(f"⚠️ 拦截到异常搜索词: {tool_args['search_query'][:50]}...")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "错误：search_query 参数过长。请提供简洁的搜索关键词，不要包含原始指令或 XML 标签。",
                    })
                    continue  # 跳过本次执行，进入下一轮让模型自我修正

                result = await self.dispatch_tool(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tikhub_tools=raw_tikhub_tools,
                    glm_tools=raw_glm_tools,
                    user_prompt=user_prompt,
                )

                # --- ⭐ 新增：强制截断逻辑 ---
                # 将结果转为字符串并检查长度
                result_str = json.dumps(result, ensure_ascii=False)

                # 设置单次工具返回的最大字符数（建议 15000 - 20000 左右）
                # 按照 1 token ≈ 1.5-2 汉字计算，20000 字符约占 10k-15k tokens
                # 这样即使调用 5 次工具，总共也就 75k tokens，远低于 128k 的限制
                MAX_CHAR_LIMIT = 15000

                if len(result_str) > MAX_CHAR_LIMIT:
                    print(f"⚠️ 工具 {tool_name} 返回内容过长 ({len(result_str)} 字符)，已触发强制截断...")
                    # 截断并补充提示，让模型知道数据不全，需要它自行总结
                    result_str = result_str[
                                     :MAX_CHAR_LIMIT] + "\n\n...(内容过长已截断，请根据现有信息分析，若信息不足请尝试更精确的搜索或减小 page_size)..."

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,  # 使用截断后的字符串
                })

        return "⚠️ 工具调用失败次数过多，已终止。"


# ===============================
# 启动测试
# ===============================


'''if __name__ == "__main__":
    async def main():
        runner = MCPAgentRunner()

        result = await runner.run(
            system_prompt="你是一个擅长联网搜索与工具切换的智能助手。",
            user_prompt="am_prompt",
        )
        print(result)

    asyncio.run(main())'''