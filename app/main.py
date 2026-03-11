import os
import asyncio
import threading
import socket
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

# ==============================================================================
# 🔥 终极黑客防御：无损高速异步转发引擎 (解决多进程打架与网络报错)
# ==============================================================================
async def handle_client(reader, writer):
    try:
        # 内部悄悄连回主程序 10307 端口
        remote_reader, remote_writer = await asyncio.open_connection('127.0.0.1', int(PORT))
        
        async def forward(src, dst):
            try:
                while True:
                    data = await src.read(8192)
                    if not data: break
                    dst.write(data)
                    await dst.drain()
            except Exception: pass
            finally:
                try: dst.close()
                except: pass

        # 双向高速流转发，彻底解决网页卡死和登录报错
        await asyncio.gather(
            forward(reader, remote_writer),
            forward(remote_reader, writer)
        )
    except Exception:
        try: writer.close()
        except: pass

def start_async_proxy():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # 开启 SO_REUSEPORT 魔法：允许多个进程同时监听同一个端口，绝不崩服！
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError: pass
        
        sock.bind(('0.0.0.0', 10308))
        sock.listen(100)
        sock.setblocking(False)
        
        coro = asyncio.start_server(handle_client, sock=sock)
        loop.run_until_complete(coro)
        print("🎈 [User Portal] Host模式专属: 10308 无损高速转发引擎已就绪！")
        loop.run_forever()
    except OSError:
        pass  # 极少数情况下没抢到端口，静默退出，绝不带着主程序崩溃
    except Exception:
        pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting EmbyPulse...")
    bot.start()
    # 🌟 启动高速转发引擎
    threading.Thread(target=start_async_proxy, daemon=True).start()
    yield
    print("🛑 Stopping EmbyPulse...")
    bot.stop()

app = FastAPI(lifespan=lifespan)

# ==============================================================================
# 🔥 底层核心护城河：Pure ASGI 协议级隐形分流器 (彻底解决依然进入后台的问题)
# ==============================================================================
class Port10308Dispatcher:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            
            # 提取所有可能暴露身份的 Host 信息
            host = headers.get(b"host", b"").decode("utf-8")
            x_fwd_port = headers.get(b"x-forwarded-port", b"").decode("utf-8")
            x_fwd_host = headers.get(b"x-forwarded-host", b"").decode("utf-8")
            
            # 只要沾了 10308 的边，不管你是 Docker 映射、Nginx 反代还是 Host 模式，一律拿下！
            if host.endswith(":10308") or x_fwd_port == "10308" or x_fwd_host.endswith(":10308"):
                path = scope.get("path", "")
                
                # 1. 协议级篡改：在 FastAPI 还没看到之前，把路径硬改成 /request
                if path == "/":
                    scope["path"] = "/request"
                    scope["raw_path"] = b"/request"
                    
                # 2. 物理铁血隔离：非安全路径，直接在底层返回 404，FastAPI 连处理的机会都没有
                allowed = ("/request", "/request_login", "/api/v1/request", "/api/proxy", "/static", "/favicon.ico")
                if not scope["path"].startswith(allowed):
                    async def send_404():
                        await send({"type": "http.response.start", "status": 404, "headers": [(b"content-type", b"text/html; charset=utf-8")]})
                        await send({"type": "http.response.body", "body": b"<h1>404 Not Found</h1><p>非法越界，访问已被系统物理拒绝。</p>"})
                    return await send_404()
                    
        await self.app(scope, receive, send)

# 注册拦截器 (注意：必须放在最前面，让它成为拦截的第一道防线)
app.add_middleware(Port10308Dispatcher)
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
