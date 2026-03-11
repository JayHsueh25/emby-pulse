import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.routers import insight
from app.core.config import PORT, SECRET_KEY, CONFIG_DIR, FONT_DIR
from app.core.database import init_db
from app.services.bot_service import bot
from app.routers import media_request
# 🔥 引入所有路由
from app.routers import views, auth, users, stats, bot as bot_router, system, proxy, report, webhook, insight, tasks, history, calendar, search, clients, gaps

# 初始化目录和数据库
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")
if not os.path.exists(CONFIG_DIR): os.makedirs(CONFIG_DIR)
if not os.path.exists(FONT_DIR): os.makedirs(FONT_DIR)
init_db()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting EmbyPulse...")
    bot.start()
    yield
    print("🛑 Stopping EmbyPulse...")
    bot.stop()

app = FastAPI(lifespan=lifespan)

# ==============================================================================
# 🔥 终极护城河：反代请求头公章识别器 (无视任何端口与网络拓扑)
# ==============================================================================
class PortalModeDispatcher:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            
            # 铁血核验：寻找 Lucky 盖的专属公章 (ASGI 规范中 HTTP 头自动转为全小写)
            if headers.get(b"x-portal-mode") == b"user":
                path = scope.get("path", "")
                
                # 1. 协议级篡改：在系统处理前，把根目录硬指向求片中心
                if path == "/":
                    scope["path"] = "/request"
                    scope["raw_path"] = b"/request"
                    
                # 2. 绝对物理隔离：非安全路径，底层直接返回 404
                allowed = ("/request", "/request_login", "/api/v1/request", "/api/proxy", "/static", "/favicon.ico")
                if not scope["path"].startswith(allowed):
                    async def send_404():
                        await send({"type": "http.response.start", "status": 404, "headers": [(b"content-type", b"text/html; charset=utf-8")]})
                        await send({"type": "http.response.body", "body": "<h1>404 Not Found</h1><p>非法越界，访问已被系统物理拒绝。</p>".encode("utf-8")})
                    return await send_404()
                    
        await self.app(scope, receive, send)

# 注册拦截器 (必须放在首位)
app.add_middleware(PortalModeDispatcher)
# ==============================================================================

# 中间件
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400*7)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# 注册路由
app.include_router(views.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(stats.router)
app.include_router(bot_router.router)
app.include_router(system.router)
app.include_router(proxy.router)
app.include_router(report.router)
app.include_router(insight.router)
app.include_router(webhook.router)
app.include_router(tasks.router)
app.include_router(history.router)
app.include_router(calendar.router)
app.include_router(media_request.router)
app.include_router(search.router)
app.include_router(clients.router)
app.include_router(gaps.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
