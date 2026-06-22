"""
Supabase 客户端 - 用于 FileCollect 的数据持久化
使用 Supabase REST API（PostgREST）直接操作数据库
"""

import os
import json
import urllib.request
import urllib.error

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://uvolvfwbzyfipzuuppqg.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InV2b2x2ZndienlmaXB6dXVwcHFnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE3OTc3NTMsImV4cCI6MjA5NzM3Mzc1M30.bHcP7mKiyRT_ISQqvpsyA3w1Mir7XAiXvR4fGghc81M')
TABLE_NAME = 'collections'


def is_configured():
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _request(method, path, data=None):
    """发送 REST 请求到 Supabase"""
    if not is_configured():
        print('[supabase] Not configured')
        return None

    url = f"{SUPABASE_URL}/rest/v1/{path}"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation',
    }

    body = json.dumps(data).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='replace')[:500]
        print(f"[supabase] HTTP {e.code} on {method} {path}: {err_body}")
        return None
    except Exception as e:
        print(f"[supabase] Error on {method} {path}: {type(e).__name__}: {e}")
        return None


def get_all_collections():
    """获取所有收集任务（返回 dict，key 为 collection id）"""
    result = _request('GET', f'{TABLE_NAME}?order=created_at.desc')
    if result is None:
        return None
    collections = {}
    for row in result:
        collections[row['id']] = {
            'id': row['id'],
            'title': row.get('title', ''),
            'description': row.get('description', ''),
            'target_email': row.get('target_email', ''),
            'allowed_types': json.loads(row.get('allowed_types', '["any"]')),
            'people': json.loads(row.get('people', '[]')),
            'max_files': row.get('max_files', 10),
            'max_size_mb': row.get('max_size_mb', 50),
            'created_at': row.get('created_at', ''),
            'emailed': row.get('emailed', False),
            'emailed_at': row.get('emailed_at'),
        }
    return collections


def save_collection(collection):
    """保存/更新一个收集任务（upsert）"""
    row = {
        'id': collection['id'],
        'title': collection.get('title', ''),
        'description': collection.get('description', ''),
        'target_email': collection.get('target_email', ''),
        'allowed_types': json.dumps(collection.get('allowed_types', ['any']), ensure_ascii=False),
        'people': json.dumps(collection.get('people', []), ensure_ascii=False),
        'max_files': collection.get('max_files', 10),
        'max_size_mb': collection.get('max_size_mb', 50),
        'created_at': collection.get('created_at', ''),
        'emailed': collection.get('emailed', False),
        'emailed_at': collection.get('emailed_at'),
    }
    # 先尝试 insert，如果冲突则 update
    result = _request('POST', TABLE_NAME, row)
    if result is None:
        # 可能是已存在，尝试 upsert
        result = _request('PATCH', f'{TABLE_NAME}?id=eq.{collection["id"]}', row)
    return result


def delete_collection(collection_id):
    """删除一个收集任务"""
    return _request('DELETE', f'{TABLE_NAME}?id=eq.{collection_id}')
