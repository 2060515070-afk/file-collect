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
            'auto_email': row.get('auto_email', False),
            'zip_name': row.get('zip_name', ''),
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
        'auto_email': collection.get('auto_email', False),
        'zip_name': collection.get('zip_name', ''),
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


# ── Supabase Storage 文件存储 ─────────────────────────────────────────
STORAGE_BUCKET = 'file-collect'


def ensure_bucket():
    """确保存储桶存在，开启大文件 TUS 续传"""
    # 先检查桶是否已存在
    url = f"{SUPABASE_URL}/storage/v1/bucket/{STORAGE_BUCKET}"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
    }
    req = urllib.request.Request(url, headers=headers, method='GET')
    try:
        urllib.request.urlopen(req, timeout=10)
        # 桶已存在，尝试更新 TUS 设置
        update_url = f"{SUPABASE_URL}/storage/v1/bucket/{STORAGE_BUCKET}"
        body = json.dumps({
            'fileSizeLimit': 524288000,  # 500MB
            'allowedMimeTypes': None,    # 允许所有类型
        }).encode('utf-8')
        req2 = urllib.request.Request(update_url, data=body, headers=headers, method='PUT')
        try:
            urllib.request.urlopen(req2, timeout=10)
        except Exception:
            pass  # 更新失败不影响使用
        return True
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"[storage] bucket check error: {e.code}")
            return False
    except Exception as e:
        print(f"[storage] bucket check error: {e}")
        return False

    # 桶不存在，创建并开启 TUS
    create_url = f"{SUPABASE_URL}/storage/v1/bucket"
    body = json.dumps({
        'id': STORAGE_BUCKET,
        'name': STORAGE_BUCKET,
        'public': False,
        'fileSizeLimit': 524288000,  # 500MB
        'allowedMimeTypes': None,    # 允许所有类型
    }).encode('utf-8')
    req = urllib.request.Request(create_url, data=body, headers=headers, method='POST')
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 409:  # 已存在
            return True
        print(f"[storage] bucket create error: {e.code}")
        return False
    return True


def upload_file(file_data, storage_path, content_type='application/octet-stream'):
    """上传文件到 Supabase Storage（服务端用）"""
    ensure_bucket()
    url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{storage_path}"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': content_type,
    }
    # 根据文件大小动态调整超时：基础 60s + 每 MB 额外 2s，最大 600s
    file_mb = len(file_data) / (1024 * 1024)
    timeout = min(60 + int(file_mb * 2), 600)
    req = urllib.request.Request(url, data=file_data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True
    except urllib.error.HTTPError as e:
        err = e.read().decode('utf-8', errors='replace')[:300]
        print(f"[storage] upload error {e.code}: {err}")
        return False
    except Exception as e:
        print(f"[storage] upload error: {e}")
        return False


def get_upload_url(storage_path):
    """获取签名上传 URL，供前端直传 Supabase Storage"""
    ensure_bucket()
    url = f"{SUPABASE_URL}/storage/v1/object/upload/sign/{STORAGE_BUCKET}/{storage_path}"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
    }
    body = json.dumps({'expiresIn': 300}).encode('utf-8')  # 5分钟有效
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            path = data.get('url', '')
            if path:
                return f"{SUPABASE_URL}/storage/v1{path}"
            return None
    except Exception as e:
        print(f"[storage] get_upload_url error: {e}")
        return None


def delete_file(storage_path):
    """从 Supabase Storage 删除文件"""
    url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{storage_path}"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
    }
    req = urllib.request.Request(url, headers=headers, method='DELETE')
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"[storage] delete error: {e}")
        return False


def get_download_url(storage_path):
    """获取文件的签名下载 URL"""
    url = f"{SUPABASE_URL}/storage/v1/object/sign/{STORAGE_BUCKET}/{storage_path}"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
    }
    body = json.dumps({'expiresIn': 3600}).encode('utf-8')  # 1小时有效
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            signed_url = data.get('signedURL', '')
            return f"{SUPABASE_URL}{signed_url}" if signed_url else None
    except Exception as e:
        print(f"[storage] sign error: {e}")
        return None


def download_file(storage_path):
    """下载文件内容"""
    url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{storage_path}"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as e:
        print(f"[storage] download error: {e}")
        return None


# ── Surveys 问卷功能 ─────────────────────────────────────────────────
SURVEYS_TABLE = 'surveys'


def get_all_surveys():
    """获取所有问卷（返回 dict，key 为 survey id）"""
    result = _request('GET', f'{SURVEYS_TABLE}?order=created_at.desc')
    if result is None:
        return None
    surveys = {}
    for row in result:
        surveys[row['id']] = {
            'id': row['id'],
            'title': row.get('title', ''),
            'description': row.get('description', ''),
            'target_email': row.get('target_email', ''),
            'questions': json.loads(row.get('questions', '[]')),
            'people': json.loads(row.get('people', '[]')),
            'responses': json.loads(row.get('responses', '{}')),
            'created_at': row.get('created_at', ''),
            'emailed': row.get('emailed', False),
            'emailed_at': row.get('emailed_at'),
            'auto_email': row.get('auto_email', False),
        }
    return surveys


def save_survey(survey):
    """保存/更新一个问卷（upsert）"""
    row = {
        'id': survey['id'],
        'title': survey.get('title', ''),
        'description': survey.get('description', ''),
        'target_email': survey.get('target_email', ''),
        'questions': json.dumps(survey.get('questions', []), ensure_ascii=False),
        'people': json.dumps(survey.get('people', []), ensure_ascii=False),
        'responses': json.dumps(survey.get('responses', {}), ensure_ascii=False),
        'created_at': survey.get('created_at', ''),
        'emailed': survey.get('emailed', False),
        'emailed_at': survey.get('emailed_at'),
        'auto_email': survey.get('auto_email', False),
    }
    result = _request('POST', SURVEYS_TABLE, row)
    if result is None:
        result = _request('PATCH', f'{SURVEYS_TABLE}?id=eq.{survey["id"]}', row)
    return result


def delete_survey(survey_id):
    """删除一个问卷"""
    return _request('DELETE', f'{SURVEYS_TABLE}?id=eq.{survey_id}')
