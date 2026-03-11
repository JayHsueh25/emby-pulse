import os
import asyncio
import threading
import socket
from contextlib import asynccontextmanager
from fastapi import FastAPI
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

# ==============================================================================
# 🔥 真·物理隔离：10308 专属 ASGI 独立引擎 (无视任何反代环境)
# ==============================================================================
async def user_portal_app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    elif scope["type"] == "http":
        path = scope.get("path", "")
        
        # 强制送去求片中心
        if path == "/":
            scope["path"] = "/request"
            scope["raw_path"] = b"/request"
            
        # 铁血隔离白名单：放行求片页面、静态资源、以及所有受密码保护的底层 API
        allowed = (
            "/request", 
            "/request_login", 
            "/static", 
            "/favicon.ico",
            "/api"
        )
        if not scope["path"].startswith(allowed):
            async def send_404():
                await send({"type": "http.response.start", "status": 404, "headers": [(b"content-type", b"text/html; charset=utf-8")]})
                await send({"type": "http.response.body", "body": "<h1>404 Not Found</h1><p>非法越界，后台管理界面已被物理阻断。</p>".encode("utf-8")})
            return await send_404()
            
        await app(scope, receive, send)
    else:
        await app(scope, receive, send)

def start_10308_server():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            try: sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError: pass
        sock.bind(('0.0.0.0', 10308))
        sock.listen(100)
    except OSError:
        return

    import uvicorn
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    config = uvicorn.Config(app=user_portal_app, log_level="critical")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    try:
        loop.run_until_complete(server.serve(sockets=[sock]))
    except BaseException:
        pass

# ==============================================================================
# 🔥 定制化纯中文启动面板
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "="*55)
    print("🚀 [系统启动] 正在初始化 EmbyPulse 主程序...")
    bot.start()
    
    # 唤醒 10308 独立守护引擎
    threading.Thread(target=start_10308_server, daemon=True).start()
    
    # 稍微等0.5秒，确保端口绑定成功后再打印面板
    await asyncio.sleep(0.5)
    
    print("🤖 [消息通知] 机器人模块已就绪")
    print(f"🌍 [核心后台] 管理员仪表盘已运行在端口: {PORT}")
    print("🎈 [用户中心] 独立求片门户已运行在端口: 10308")
    print("✅ [系统状态] 物理隔离双引擎初始化完成，安全运行中！")
    print("="*55 + "\n")
    
    yield
    
    print("\n" + "="*55)
    print("🛑 [系统关闭] 正在停止 EmbyPulse 服务...")
    bot.stop()
    print("💤 [系统关闭] 所有服务已安全退出。")
    print("="*55 + "\n")
# ==============================================================================

app = FastAPI(lifespan=lifespan)

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
