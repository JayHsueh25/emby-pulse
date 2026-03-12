import sqlite3
import logging
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional
from app.core.database import query_db, DB_PATH

logger = logging.getLogger("uvicorn")

router = APIRouter(prefix="/api/notifications", tags=["系统通知"])

class MarkReadReq(BaseModel):
    id: Optional[int] = None

def ensure_table_exists():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS sys_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            title TEXT,
            message TEXT,
            is_read INTEGER DEFAULT 0,
            action_url TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        # 🔥 无损热更新：为旧表自动增加 is_cleared 隐藏标记列
        try:
            c.execute("ALTER TABLE sys_notifications ADD COLUMN is_cleared INTEGER DEFAULT 0")
        except:
            pass # 如果已经有了就会报错，忽略即可
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[通知中心] 自动建表失败: {e}")

@router.get("")
@router.get("/")
async def get_notifications(limit: int = 10, history: bool = False):
    ensure_table_exists()
    try:
        # 未读数量只统计没被清空的
        count_res = query_db("SELECT COUNT(*) as c FROM sys_notifications WHERE is_read = 0 AND is_cleared = 0")
        unread_count = count_res[0]['c'] if count_res else 0

        # 🔥 核心逻辑：如果是拉取历史记录，就无视 is_cleared 标志全部拉出；否则只拉取未被清理的
        if history:
            rows = query_db("SELECT * FROM sys_notifications ORDER BY created_at DESC LIMIT ?", (limit,))
        else:
            rows = query_db("SELECT * FROM sys_notifications WHERE is_cleared = 0 ORDER BY created_at DESC LIMIT ?", (limit,))
        
        notifications = []
        if rows:
            for r in rows:
                notifications.append({
                    "id": r["id"],
                    "type": r["type"],
                    "title": r["title"],
                    "message": r["message"],
                    "is_read": r["is_read"],
                    "action_url": r["action_url"],
                    "created_at": r["created_at"]
                })
        return {"success": True, "unread_count": unread_count, "items": notifications}
    except Exception as e:
        print(f"❌ [通知中心] 发生异常: {e}")
        return {"success": False, "msg": str(e)}

@router.post("/read")
async def mark_as_read(req: MarkReadReq):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        if req.id:
            cur.execute("UPDATE sys_notifications SET is_read = 1 WHERE id = ?", (req.id,))
        else:
            cur.execute("UPDATE sys_notifications SET is_read = 1 WHERE is_read = 0 AND is_cleared = 0")
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "msg": str(e)}

@router.delete("/clear")
async def clear_notifications():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # 🔥 核心逻辑：不再是 DELETE FROM，而是软删除（同时标记为已读并隐藏）
        cur.execute("UPDATE sys_notifications SET is_cleared = 1, is_read = 1 WHERE is_cleared = 0")
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "msg": str(e)}

@router.get("/test_push")
async def test_push_notification():
    ensure_table_exists()
    try:
        from app.core.database import add_sys_notification
        add_sys_notification(
            notify_type="system",
            title="✅ 测试通知成功接入",
            message="如果你看到了这条消息，说明从写入到读取的链路已经完全打通！",
            action_url="/"
        )
        return {"success": True, "msg": "测试通知已注入！"}
    except Exception as e:
        return {"success": False, "msg": f"注入失败: {str(e)}"}