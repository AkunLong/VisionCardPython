# 全局日志的配置
# app/logging_config.py

import logging
import sys
import os
from datetime import datetime

# 更加丰富的格式定义：
# [%(asctime)s] 时间
# [%(levelname)-8s] 级别（固定8位宽度，对齐美观）
# [%(process)d] 进程ID（异步或多进程任务有用）
# [%(name)s:%(funcName)s:%(lineno)d] 模块名:函数名:行号
# %(message)s 日志正文
LOG_FORMAT = (
    "[%(asctime)s.%(msecs)03d] "
    "[%(levelname).4s] "
    "[P%(process)d] "
    "[%(name)s:%(funcName)s:%(lineno)d] "
    "- %(message)s"
)

# 时间格式精确到秒
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

def setup_logging(level=logging.INFO):
    """
    配置全局日志系统
    """
    # 确保日志目录存在（如果以后需要存文件）
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 1. 基础配置
    log_config = {
        "level": level,
        "format": LOG_FORMAT,
        "datefmt": DATE_FORMAT,
        "handlers": [
            # 输出到控制台
            logging.StreamHandler(sys.stdout),
            # 同时输出到本地文件，方便追溯 Token 暴涨的历史记录
            logging.FileHandler(
                f"{log_dir}/app_{datetime.now().strftime('%Y%m%d')}.log",
                encoding="utf-8"
            ),
        ],
    }

    # 应用配置
    logging.basicConfig(**log_config)

    # 2. 特殊处理：降低某些第三方库过多的日志干扰（可选）
    # 比如 httpx 的请求日志如果觉得烦，可以调高它的级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)

    logging.info("🚀 日志系统初始化完成，格式已增强")

# 使用建议：
# setup_logging(logging.DEBUG)  # 开发环境
# setup_logging(logging.INFO)   # 生产环境