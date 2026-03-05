from fastapi import APIRouter, Response
from app.core.config import cfg
import requests
import urllib.parse
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 初始化日志
logger = logging.getLogger("uvicorn")
router = APIRouter()

# 🔥 工业级抗压处理：使用全局 Session 复用连接，并设置指数退避重试
session = requests.Session()
retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
session.mount('http://', HTTPAdapter(max_retries=retries, pool_connections=100, pool_maxsize=100))
session.mount('https://', HTTPAdapter(max_retries=retries, pool_connections=100, pool_maxsize=100))

# 图片 ID 映射缓存
smart_image_cache = {}

def get_real_image_id_robust(item_id: str):
    """智能 ID 转换（解决剧集封面变单集截图的问题）"""
    key = cfg.get("emby_api_key")
    host = cfg.get("emby_host")
    if not key or not host: return item_id

    params_base = {"api_key": key}

    try:
        url_a = f"{host}/emby/Items/{item_id}"
        res_a = session.get(url_a, params={**params_base, "Fields": "SeriesId,ParentId"}, timeout=3)
        if res_a.status_code == 200:
            data = res_a.json()
            if data.get("SeriesId"): return data['SeriesId']
            if data.get("Type") == "Episode" and data.get("ParentId"): return data['ParentId']
    except: pass

    try:
        url_b = f"{host}/emby/Items/{item_id}/Ancestors"
        res_b = session.get(url_b, params=params_base, timeout=3)
        if res_b.status_code == 200:
            for ancestor in res_b.json():
                if ancestor.get("Type") == "Series": return ancestor['Id']
                if ancestor.get("Type") == "Season" and not ancestor.get("SeriesId"): return ancestor['Id']
    except: pass

    try:
        url_c = f"{host}/emby/Items"
        res_c = session.get(url_c, params={**params_base, "Ids": item_id, "Fields": "SeriesId", "Recursive": "true"}, timeout=3)
        if res_c.status_code == 200:
            items = res_c.json().get("Items", [])
            if items and items[0].get("SeriesId"): return items[0]['SeriesId']
    except: pass

    return item_id

@router.get("/api/proxy/image/{item_id}/{img_type}")
def proxy_image(item_id: str, img_type: str):
    key = cfg.get("emby_api_key"); host = cfg.get("emby_host")
    if not key or not host: return Response(status_code=404)
    try:
        target_id = get_real_image_id_robust(item_id) if img_type.lower() == 'primary' else item_id
        url = f"{host}/emby/Items/{target_id}/Images/{img_type}?maxHeight=600&maxWidth=400&quality=90&api_key={key}"
        resp = session.get(url, timeout=10, stream=True)
        if resp.status_code == 200:
            return Response(content=resp.content, media_type=resp.headers.get("Content-Type", "image/jpeg"), headers={"Cache-Control": "public, max-age=3600"})
        
        if resp.status_code == 404 and target_id != item_id:
            fallback_url = f"{host}/emby/Items/{item_id}/Images/{img_type}?maxHeight=600&maxWidth=400&quality=90&api_key={key}"
            fallback_resp = session.get(fallback_url, timeout=10, stream=True)
            if fallback_resp.status_code == 200:
                 return Response(content=fallback_resp.content, media_type=fallback_resp.headers.get("Content-Type", "image/jpeg"), headers={"Cache-Control": "public, max-age=3600"})
    except Exception: pass
    return Response(status_code=404)

@router.get("/api/proxy/smart_image")
def proxy_smart_image(item_id: str, name: str = "", year: str = "", type: str = "Primary"):
    """
    🔥 三级海报防裂兜底引擎 (带极速缓存与断连保护)：
    """
    key = cfg.get("emby_api_key")
    host = cfg.get("emby_host")
    if not key or not host: return Response(status_code=404)

    # 1. 缓存拦截：如果缓存里是外部 URL (比如 TMDB)，直接转发
    cached_result = smart_image_cache.get(item_id)
    if cached_result and str(cached_result).startswith('http'):
        try:
            proxy = cfg.get("proxy_url")
            proxies = {"https": proxy, "http": proxy} if proxy else None
            # 这里的 timeout 放宽点，防止网络抖动抛错
            resp = session.get(cached_result, proxies=proxies, timeout=10, stream=True)
            if resp.status_code == 200:
                return Response(content=resp.content, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
        except Exception as e:
            logger.error(f"从缓存获取 TMDB 图片失败: {e}")
            pass # 失败则继续往下走尝试重新获取

    target_id = cached_result if cached_result and not str(cached_result).startswith('http') else item_id
    img_type = type
    params = "?maxWidth=1920&quality=80" if img_type.lower() == 'backdrop' else "?maxHeight=800&maxWidth=600&quality=90"
    
    # 2. 第 1 级防御：正常请求 Emby
    if img_type.lower() == 'primary' and target_id == item_id:
        target_id = get_real_image_id_robust(target_id)
        
    url = f"{host}/emby/Items/{target_id}/Images/{img_type}{params}&api_key={key}"
    try:
        resp = session.get(url, timeout=5, stream=True)
        if resp.status_code == 200:
            return Response(content=resp.content, media_type=resp.headers.get("Content-Type", "image/jpeg"), headers={"Cache-Control": "public, max-age=86400"})
    except requests.exceptions.RequestException as e: 
        logger.debug(f"Emby 图片请求超时或断开: {e}")

    # 3. 第 2 级防御：洗版名字搜索兜底
    clean_name = name.split(' - ')[0].strip() if name else ""
    if clean_name:
        try:
            search_url = f"{host}/emby/Items?SearchTerm={urllib.parse.quote(clean_name)}&IncludeItemTypes=Movie,Series,Episode&Recursive=true&api_key={key}"
            s_resp = session.get(search_url, timeout=5)
            if s_resp.status_code == 200:
                items = s_resp.json().get("Items", [])
                if items:
                    new_id = items[0]["Id"]
                    if items[0]["Type"] in ["Episode", "Season", "Series"]:
                        new_id = get_real_image_id_robust(new_id)
                    smart_image_cache[item_id] = new_id 
                    
                    new_url = f"{host}/emby/Items/{new_id}/Images/{img_type}{params}&api_key={key}"
                    n_resp = session.get(new_url, timeout=5, stream=True)
                    if n_resp.status_code == 200:
                        return Response(content=n_resp.content, media_type=n_resp.headers.get("Content-Type", "image/jpeg"), headers={"Cache-Control": "public, max-age=86400"})
        except requests.exceptions.RequestException: pass

    # 4. 第 3 级防御：TMDB 终极兜底
    tmdb_key = cfg.get("tmdb_api_key")
    if clean_name and tmdb_key:
        try:
            proxy = cfg.get("proxy_url")
            proxies = {"https": proxy, "http": proxy} if proxy else None
            
            tmdb_url = f"https://api.themoviedb.org/3/search/multi?api_key={tmdb_key}&language=zh-CN&query={urllib.parse.quote(clean_name)}"
            t_resp = session.get(tmdb_url, proxies=proxies, timeout=5)
            
            if t_resp.status_code == 200:
                results = t_resp.json().get("results", [])
                for res in results:
                    if res.get("media_type") in ["movie", "tv"]:
                        img_path = res.get("backdrop_path") if img_type.lower() == 'backdrop' else res.get("poster_path")
                        if img_path:
                            tmdb_img_url = f"https://image.tmdb.org/t/p/w500{img_path}"
                            smart_image_cache[item_id] = tmdb_img_url 
                            
                            final_resp = session.get(tmdb_img_url, proxies=proxies, timeout=8, stream=True)
                            if final_resp.status_code == 200:
                                return Response(content=final_resp.content, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
                        break
        except requests.exceptions.RequestException as e:
            logger.error(f"TMDB 兜底网络异常 [{clean_name}]: {e}")
            
    # 5. 返回 404，前端会自动用 No Cover 占位图兜住
    return Response(status_code=404)

@router.get("/api/proxy/user_image/{user_id}")
def proxy_user_image(user_id: str, tag: str = None):
    key = cfg.get("emby_api_key"); host = cfg.get("emby_host")
    if not key: return Response(status_code=404)
    try:
        url = f"{host}/emby/Users/{user_id}/Images/Primary?width=200&height=200&mode=Crop&quality=90&api_key={key}"
        if tag: url += f"&tag={tag}"
        resp = session.get(url, timeout=3)
        if resp.status_code == 200:
            return Response(content=resp.content, media_type=resp.headers.get("Content-Type", "image/jpeg"))
    except: pass
    return Response(status_code=404)