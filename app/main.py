import os
import asyncio
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
# 🔥 核心防御：10308 端口专属隐形分流器 (求片中心独立出入口)
# ==============================================================================
@app.middleware("http")
async def port_10308_dispatcher(request: Request, call_next):
    # 获取请求的 Host (例如 192.168.1.100:10308)
    host_header = request.headers.get("host", "")
    
    # 铁律：只要是以 :10308 结尾的请求，全部打入普通用户通道
    if host_header.endswith(":10308"):
        path = request.url.path
        
        # 1. 隐形重写：访问根目录当做访问求片中心
        if path == "/":
            request.scope["path"] = "/request"
            
        # 2. 物理隔绝：只放行普通用户需要的路径，其他后台路由一律假死拦截
        allowed_prefixes = (
            "/request", "/request_login", 
            "/api/v1/request", "/api/proxy/smart_image", 
            "/static", "/favicon.ico"
        )
        if not request.scope["path"].startswith(allowed_prefixes):
            return HTMLResponse("<h1>404 Not Found</h1>", status_code=404)
            
    return await call_next(request)
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

# ==============================================================================
# 🔥 原生双端口启动引擎 (完美适配 Host 模式)
# ==============================================================================
if __name__ == "__main__":
    import uvicorn

    async def start_dual_ports():
        print(f"🌍 [Admin Portal] 管理员后台已运行在端口: {PORT}")
        print(f"🎈 [User Portal]  求片中心已运行在端口: 10308")
        
        # 实例 1: 监听原有后台端口 (默认 10307)
        config_admin = uvicorn.Config(app, host="0.0.0.0", port=PORT)
        server_admin = uvicorn.Server(config_admin)
        
        # 实例 2: 强制监听用户专属端口 (10308)
        config_user = uvicorn.Config(app, host="0.0.0.0", port=10308)
        server_user = uvicorn.Server(config_user)
        
        # 并发启动两个端口监听
        await asyncio.gather(server_admin.serve(), server_user.serve())

    # 运行双端口服务
    asyncio.run(start_dual_ports())