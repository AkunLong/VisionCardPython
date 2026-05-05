# -*- coding: utf-8 -*-
# app/main.py
# 职责：FastAPI 核心入口，负责鉴权、路由分发、挂载 Gradio UI
# uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# uvicorn app.main:app  --host 0.0.0.0 --port 8000


from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse, HTMLResponse,FileResponse
from fastapi.templating import Jinja2Templates
import threading
from contextlib import asynccontextmanager
import gradio as gr
import os
# 1. 导入原有业务逻辑
from app.api.scripts import router as scripts_router
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.pay import router as pay_router
from app.api.search import router as search_router
from app.infra.db import init_db
from app.workers.job_worker import start_worker
from app.workers.job_clean import cleanup_jobs
from app.logging_cofig import setup_logging
from app.orchestrator.steps.task_news import scheduler, setup_scheduler

# 2. 导入鉴权与 UI
from app.auth.auth_jwt import decode_token
from ui.app_main import demo  # 👈 导入你刚刚改好的 Gradio 界面对象

# 初始化日志
setup_logging()

# 初始化模板与静态资源
templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(fapi: FastAPI):
    # --- Startup: 应用启动逻辑 ---

    # 🌟 极简去重：只要 scheduler 没跑，就代表是第一次初始化
    if not scheduler.running:
        print("🚀 [System] Initializing core services...")

        # 1. 启动定时任务调度器
        try:
            setup_scheduler()
            scheduler.start()
            print("✅ [System] Scheduler (Cron Jobs) started.")
        except Exception as e:
            print(f"❌ [System] Failed to start scheduler: {e}")

        # 2. 初始化数据库
        init_db()

        # 3. 启动任务处理 Worker
        start_worker()

        # 4. 启动任务清理线程
        cleanup_thread = threading.Thread(target=cleanup_jobs, daemon=True)
        cleanup_thread.start()
        print("✅ [System] Workers and Cleanup thread are running.")

    yield  # 🚀 这里是程序运行的分界线

    # --- Shutdown: 应用关闭逻辑 ---
    if scheduler.running:
        print("🛑 [System] Shutting down scheduler...")
        scheduler.shutdown()


app = FastAPI(lifespan=lifespan, title="VideoAgent 平台接口文档")

# 获取当前 main.py 所在的 app 目录的父目录（即项目根目录）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 拼接出 ui 目录下的图标路径
FAVICON_PATH = os.path.join(BASE_DIR, "ui", "APP_ICON_SMALL.png")

@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    if os.path.exists(FAVICON_PATH):
        # 显式指定为 image/png
        return FileResponse(FAVICON_PATH, media_type="image/png")
    return Response(status_code=404)


# 如果你有本地静态资源（如视频、图片），取消下面这行的注释
# app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ============================
# 🛡️ 核心鉴权中间件 (守门员)
# ============================
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    raw_path = request.url.path
    path = raw_path.rstrip("/") if len(raw_path) > 1 else raw_path

    # 静态资源
    if any(raw_path.endswith(ext) for ext in [
        ".css", ".js", ".png", ".jpg", ".mp4",
        ".ico", ".svg", ".json"
    ]):
        return await call_next(request)

    # Gradio 内部 API
    if path.startswith("/app/gradio_api"):
        return await call_next(request)

    # 公开 API
    if path.startswith(("/auth", "/search", "/pay", "/scripts", "/health")):
        return await call_next(request)

    # Swagger
    if path.startswith(("/docs", "/redoc", "/openapi.json")):
        return await call_next(request)

    token = request.cookies.get("access_token")
    user_id = decode_token(token) if token else request.headers.get("x-user-id")
    request.state.user_id = user_id

    if path == "/login" and user_id:
        return RedirectResponse(url="/app")

    if request.method == "GET":
        if path not in ["/", "/login", "/health", "/favicon.ico"] and not user_id:
            return RedirectResponse(url="/login")

    return await call_next(request)




# ============================
# 📄 基础路由
# ============================
@app.get("/", response_class=RedirectResponse)
async def root():
    """根路径自动跳转到登录页"""
    return "/login"


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """渲染可灵风格的 HTML 登录页面"""
    return templates.TemplateResponse("app_login.html", {"request": request})


@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/manifest.json", include_in_schema=False)
async def manifest():
    return Response(content="{}", media_type="application/json")


# ============================
# 注册业务 API 路由
# ============================
app.include_router(scripts_router)
app.include_router(auth_router)
app.include_router(pay_router)
app.include_router(search_router)
app.include_router(admin_router)

# ============================
# 🎡 挂载 Gradio 工作台
# ============================
# 将 ui/app_main.py 里的 demo 挂载到 /app
# 必须放在最后挂载，确保中间件和路由都已准备就绪
app = gr.mount_gradio_app(app, demo, path="/app",footer_links=[])

if __name__ == "__main__":
    import uvicorn

    # 建议生产环境关闭 reload=True
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
