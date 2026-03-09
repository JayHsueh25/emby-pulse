import sqlite3
import os
import requests
import json
from app.core.config import cfg, DB_PATH

def init_db():
    # 确保数据库目录存在
    db_dir = os.path.dirname(DB_PATH)
    if not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except: pass

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # 0. 播放记录表
        c.execute('''
            CREATE TABLE IF NOT EXISTS PlaybackActivity (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                UserId TEXT,
                UserName TEXT,
                ItemId TEXT,
                ItemName TEXT,
                PlayDuration INTEGER,
                DateCreated DATETIME DEFAULT CURRENT_TIMESTAMP,
                Client TEXT,
                DeviceName TEXT
            )
        ''')
        
        # 1. 机器人专属配置表
        c.execute('''CREATE TABLE IF NOT EXISTS users_meta (
                        user_id TEXT PRIMARY KEY,
                        expire_date TEXT,
                        note TEXT,
                        created_at TEXT
                    )''')
        
        # 2. 邀请码表
        c.execute('''CREATE TABLE IF NOT EXISTS invitations (
                        code TEXT PRIMARY KEY,
                        days INTEGER,        -- 有效期天数 (-1为永久)
                        used_count INTEGER DEFAULT 0,
                        max_uses INTEGER DEFAULT 1,
                        created_at TEXT,
                        used_at DATETIME,
                        used_by TEXT,
                        status INTEGER DEFAULT 0,
                        template_user_id TEXT -- 绑定的权限模板用户
                    )''')
        
        try: c.execute("ALTER TABLE invitations ADD COLUMN template_user_id TEXT")
        except: pass

        # 3. 追剧日历本地缓存表
        c.execute('''CREATE TABLE IF NOT EXISTS tv_calendar_cache (
                        id TEXT PRIMARY KEY,
                        series_id TEXT,
                        season INTEGER,
                        episode INTEGER,
                        air_date TEXT,
                        status TEXT,
                        data_json TEXT
                    )''')

        # 4. 求片资源主表
        c.execute('''
            CREATE TABLE IF NOT EXISTS media_requests (
                tmdb_id INTEGER,
                media_type TEXT,
                title TEXT,
                year TEXT,
                poster_path TEXT,
                status INTEGER DEFAULT 0,
                season INTEGER DEFAULT 0,
                reject_reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tmdb_id, season)
            )
        ''')

        # 5. 求片用户关联表
        c.execute('''
            CREATE TABLE IF NOT EXISTS request_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tmdb_id INTEGER,
                user_id TEXT,
                username TEXT,
                season INTEGER DEFAULT 0,
                requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tmdb_id, user_id, season)
            )
        ''')
        
        # 6. 质量盘点忽略名单
        c.execute('''
            CREATE TABLE IF NOT EXISTS insight_ignores (
                item_id TEXT PRIMARY KEY,
                item_name TEXT,
                ignored_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # 7. 缺集管理记录表
        c.execute('''
            CREATE TABLE IF NOT EXISTS gap_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                series_id TEXT,
                series_name TEXT,
                season_number INTEGER,
                episode_number INTEGER,
                status INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(series_id, season_number, episode_number)
            )
        ''')

        conn.commit()
        conn.close()
        print("✅ Database initialized.")
    except Exception as e: 
        print(f"❌ DB Init Error: {e}")


# --- 魔法工具：将带 ? 的 SQL 转换为纯字符串 ---
def _interpolate_sql(query: str, args: tuple) -> str:
    if not args: return query
    parts = query.split('?')
    if len(parts) - 1 != len(args): return query # 防止异常
    res = parts[0]
    for i, arg in enumerate(args):
        if isinstance(arg, (int, float)): val = str(arg)
        elif arg is None: val = "NULL"
        else: val = f"'{str(arg).replace(chr(39), chr(39)+chr(39))}'" # 防注入单引号转义
        res += val + parts[i+1]
    return res


def query_db(query, args=(), one=False):
    # ==========================================
    # 🔥 双擎路由拦截器
    # ==========================================
    mode = cfg.get("playback_data_mode", "sqlite")
    is_playback_query = "PlaybackActivity" in query or "PlaybackReporting" in query
    
    if mode == "api" and is_playback_query:
        # 如果是查播放数据，且开启了 API 模式 -> 强行拦截发给 Emby 插件！
        host = cfg.get("emby_host")
        token = cfg.get("emby_api_key")
        if host and token:
            full_sql = _interpolate_sql(query, args)
            url = f"{host.rstrip('/')}/emby/user_usage_stats/submit_custom_query"
            headers = {"X-Emby-Token": token, "Content-Type": "application/json"}
            payload = {"CustomQueryString": full_sql}
            
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=20)
                if res.status_code == 200:
                    data = res.json()
                    # 抹平差异：API 返回的是字典列表，我们在后续业务代码中可以直接使用，完美兼容 sqlite3.Row
                    if query.strip().upper().startswith("SELECT"):
                        return (data[0] if data else None) if one else data
                    return True
                else:
                    print(f"API 路由查询失败: HTTP {res.status_code}")
            except Exception as e:
                print(f"API 路由网络异常: {e}")
        # 如果 API 失败或未配置，平滑降级回 sqlite 模式
    
    # ==========================================
    # 🚂 原版 SQLite 执行器 (处理本表及降级情况)
    # ==========================================
    if not os.path.exists(DB_PATH): return None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query, args)
        if query.strip().upper().startswith("SELECT"):
            rv = cur.fetchall()
            conn.close()
            return (rv[0] if rv else None) if one else rv
        else:
            conn.commit()
            conn.close()
            return True
    except Exception as e: 
        print(f"SQL Error: {e}")
        return None

def get_base_filter(user_id_filter):
    where = "WHERE 1=1"
    params = []
    
    if user_id_filter and user_id_filter != 'all':
        where += " AND UserId = ?"
        params.append(user_id_filter)
    
    hidden = cfg.get("hidden_users")
    if (not user_id_filter or user_id_filter == 'all') and hidden and len(hidden) > 0:
        placeholders = ','.join(['?'] * len(hidden))
        where += f" AND UserId NOT IN ({placeholders})"
        params.extend(hidden)
        
    return where, params