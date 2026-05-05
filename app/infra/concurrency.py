# 异步并发限制配置
# app/infra/concurrency.py
from app.config import settings
import asyncio

# LLM大模型的并发设置
LLM_SEMAPHORE = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)

# 图像大模型的并发设置
IMAGE_SEMAPHORE = asyncio.Semaphore(settings.IMAGE_MAX_CONCURRENCY)


# 语音大模型的并发设置
TTS_SEMAPHORE = asyncio.Semaphore(settings.TTS_MAX_CONCURRENCY)