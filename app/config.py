# 环境变量配置文件
# app/config.py

import os

# 环境变量初始化
from dotenv import load_dotenv
load_dotenv()

class Settings:
    # ========================
    # 基础环境
    # ========================

    TEST = os.getenv("TEST", "False").lower() in ("true", "1", "t")
    LOCAL = os.getenv("LOCAL", "False").lower() in ("true", "1", "t")

    ENV = os.getenv("ENV", "dev")  # dev / prod
    DEBUG = ENV != "prod"
    DEBUG_MODE = True


    # 账户密码
    ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

    # ========================
    # LLM Provider 选择
    # ========================

    # openai / deepseek / qwen
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")

    # ========================
    # Zhipu
    # ========================
    GLM_MCP_BASE_URL = os.getenv("GLM_MCP_BASE_URL", "")
    GLM_API_KEY = os.getenv("GLM_API_KEY", "")

    # ========================
    # DeepSeek
    # ========================
    #DEEPSEEK_API_KEY = '123'
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    # ========================
    # QWEN
    # ========================
    #QWEN_API_KEY = '123'
    QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
    QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    # Tikhub配置
    TIKHUB_MCP_BASE_URL = os.getenv("TIKHUB_MCP_BASE_URL", "")
    TIKHUB_API_KEY = os.getenv("TIKHUB_API_KEY", "")

    # Minimax配置
    #MINIMAX_API_KEY = '123'
    MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
    MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1/t2a_v2")

    # 即梦的配置
    JIMENG_API_KEY = os.getenv("JIMENG_API_KEY", "")
    JIMENG_SECRET_KEY = os.getenv("JIMENG_SECRET_KEY", "")

    PIXIAN_APP_ID = os.getenv("PIXIAN_APP_ID", "")
    PIXIAN_SECRET = os.getenv("PIXIAN_SECRET", "")

    # ========================
    # 并发控制（infra 使用）
    # ========================
    # LLM并发
    LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "10"))
    # 图像并发
    IMAGE_MAX_CONCURRENCY = int(os.getenv("IMAGE_MAX_CONCURRENCY", "1"))
    # 任务并发
    JOB_MAX_CONCURRENCY= int(os.getenv("JOB_MAX_CONCURRENCY", "3"))
    # 语音并发
    TTS_MAX_CONCURRENCY= int(os.getenv("JOB_MAX_CONCURRENCY", "2"))


    # ========================
    # 任务最大尝试次数
    # ========================
    MAX_TASK_RETRIES = int(os.getenv("MAX_TASK_RETRIES ", "5"))

    # ========================
    # Job & 系统参数
    # ========================

    JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", str(60 * 30)))  # 30 分钟
    JOB_CLEANUP_INTERVAL = int(os.getenv("JOB_CLEANUP_INTERVAL", "60"))  # 秒


    # ========================
    # OSS / 存储（后续用）
    # ========================
    # 阿里云OSS的配置
    OSS_ACCESS_KEY = os.getenv("ALIYUN_OSS_KEY_ID", "")
    OSS_SECRET_KEY = os.getenv("ALIYUN_OSS_KEY_SE", "")
    OSS_INTERNAL_ENDPOINT = os.getenv("ALIYUN_OSS_INTERNAL_ENDPOINT", "https://oss-cn-beijing-internal.aliyuncs.com")
    OSS_PUBLIC_ENDPOINT = os.getenv("ALIYUN_OSS_PUBLIC_ENDPOINT", "https://oss-cn-beijing.aliyuncs.com")
    OSS_BUCKET_TEMP_NAME = os.getenv("ALIYUN_OSS_TEMP_BUCKET_NAME", "")
    OSS_BUCKET_SAVE_NAME = os.getenv("ALIYUN_OSS_SAVE_BUCKET_NAME", "")


    # 阿里企业邮箱的配置
    ALIYUN_SMTP_SERVER = os.getenv("ALIYUN_SMTP_SERVER", "smtp.mxhichina.com")
    ALIYUN_SMTP_PORT = os.getenv("ALIYUN_SMTP_PORT", 465)
    ALIYUN_SMTP_USER = os.getenv("ALIYUN_SMTP_USER", "no-reply@videotl.com")
    ALIYUN_SMTP_PASS = os.getenv("ALIYUN_SMTP_PASS", "")



    # ========================
    # 数据库（后续用）
    # ========================
    DATABASE_URL = os.getenv("DATABASE_URL", "")

    # ========================
    # 微信登录鉴权
    # ========================
    WECHAT_APP_ID = os.getenv("WECHAT_APP_ID", "")
    WECHAT_APP_SECRET = os.getenv("WECHAT_APP_SECRET", "")


    # ========================
    # 扣分价格表
    # ========================
    JOB_PRICES = {
        # 全网搜索情报
        "create_incident_news": 30,
        "write_video_script": 10,
        "evaluation_video_script":5,
        "edit_video_script":10,
        "make_audio": 30,
        "generate_subtitles":5,
        "search_video_materials":5,
        "generate_hot_title":5,
        "generate_image_prompt":5,
        "generate_image":10,
        "generate_image_edit":10,
    }

# 导出 settings 实例，供其他模块直接使用
settings = Settings()