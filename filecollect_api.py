"""
FileCollect API 客户端 - 用于程序化操作文件收集站
用法：python filecollect_api.py <command> [args...]
"""

import sys
import json
import urllib.request
import urllib.error

BASE_URL = 'https://565241.xyz'
API_KEY = 'fc-api-key-2026'

def _api(method, path, data=None):
    """发送 API 请求"""
    url = f"{BASE_URL}{path}"
    headers = {
        'X-API-Key': API_KEY,
        'Content-Type': 'application/json',
        'User-Agent': 'FileCollect-API-Client/1.0',
    }
    body = json.dumps(data).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode('utf-8', errors='replace')
        try:
            return json.loads(err)
        except:
            return {'error': f'HTTP {e.code}: {err[:500]}'}
    except Exception as e:
        return {'error': str(e)}

def list_collections():
    """列出所有收集任务"""
    return _api('GET', '/api/v1/collections')

def get_collection(collection_id):
    """获取收集任务详情"""
    return _api('GET', f'/api/v1/collections/{collection_id}')

def create_collection(title, description='', target_email='', people=None,
                      allowed_types=None, max_files=10, max_size_mb=50,
                      auto_email=False, zip_name=''):
    """创建新的收集任务"""
    data = {
        'title': title,
        'description': description,
        'target_email': target_email,
        'people': people or [],
        'allowed_types': allowed_types or ['any'],
        'max_files': max_files,
        'max_size_mb': max_size_mb,
        'auto_email': auto_email,
        'zip_name': zip_name,
    }
    return _api('POST', '/api/v1/collections', data)

def delete_collection(collection_id):
    """删除收集任务"""
    return _api('DELETE', f'/api/v1/collections/{collection_id}')

def add_people(collection_id, names):
    """添加人员"""
    return _api('POST', f'/api/v1/collections/{collection_id}/people', {'names': names})

def remove_person(collection_id, person_id):
    """移除人员"""
    return _api('DELETE', f'/api/v1/collections/{collection_id}/people/{person_id}')

def send_email(collection_id, email=None):
    """发送邮件"""
    data = {}
    if email:
        data['email'] = email
    return _api('POST', f'/api/v1/collections/{collection_id}/send-email', data)

def reset_person(collection_id, person_id):
    """重置提交状态"""
    return _api('POST', f'/api/v1/collections/{collection_id}/reset-person/{person_id}')

def download_zip(collection_id, save_path=None):
    """下载 ZIP 文件"""
    url = f"{BASE_URL}/api/v1/collections/{collection_id}/download-zip?api_key={API_KEY}"
    if not save_path:
        save_path = f"{collection_id}.zip"
    try:
        urllib.request.urlretrieve(url, save_path)
        return {'success': True, 'path': save_path}
    except Exception as e:
        return {'error': str(e)}

def help_text():
    return """
FileCollect API 客户端
======================

用法: python filecollect_api.py <command> [args...]

命令:
  list                          列出所有收集任务
  get <collection_id>           获取任务详情
  create <title> [email] [people_json]  创建任务
  delete <collection_id>        删除任务
  add-people <collection_id> <name1> [name2] ...  添加人员
  remove-person <collection_id> <person_id>  移除人员
  send-email <collection_id> [email]  发送邮件
  reset <collection_id> <person_id>  重置提交状态
  download <collection_id> [path]  下载 ZIP

示例:
  python filecollect_api.py list
  python filecollect_api.py create "2456班作业收集" "2060515070@qq.com" '["张三","李四","王五"]'
  python filecollect_api.py get abc123def456
  python filecollect_api.py send-email abc123def456
"""

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(help_text())
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == 'list':
        result = list_collections()
    elif cmd == 'get':
        if len(sys.argv) < 3:
            print("用法: get <collection_id>")
            sys.exit(1)
        result = get_collection(sys.argv[2])
    elif cmd == 'create':
        if len(sys.argv) < 3:
            print("用法: create <title> [email] [people_json]")
            sys.exit(1)
        title = sys.argv[2]
        email = sys.argv[3] if len(sys.argv) > 3 else ''
        people = json.loads(sys.argv[4]) if len(sys.argv) > 4 else []
        result = create_collection(title, target_email=email, people=people)
    elif cmd == 'delete':
        if len(sys.argv) < 3:
            print("用法: delete <collection_id>")
            sys.exit(1)
        result = delete_collection(sys.argv[2])
    elif cmd == 'add-people':
        if len(sys.argv) < 4:
            print("用法: add-people <collection_id> <name1> [name2] ...")
            sys.exit(1)
        result = add_people(sys.argv[2], sys.argv[3:])
    elif cmd == 'remove-person':
        if len(sys.argv) < 4:
            print("用法: remove-person <collection_id> <person_id>")
            sys.exit(1)
        result = remove_person(sys.argv[2], sys.argv[3])
    elif cmd == 'send-email':
        if len(sys.argv) < 3:
            print("用法: send-email <collection_id> [email]")
            sys.exit(1)
        email = sys.argv[3] if len(sys.argv) > 3 else None
        result = send_email(sys.argv[2], email)
    elif cmd == 'reset':
        if len(sys.argv) < 4:
            print("用法: reset <collection_id> <person_id>")
            sys.exit(1)
        result = reset_person(sys.argv[2], sys.argv[3])
    elif cmd == 'download':
        if len(sys.argv) < 3:
            print("用法: download <collection_id> [save_path]")
            sys.exit(1)
        path = sys.argv[3] if len(sys.argv) > 3 else None
        result = download_zip(sys.argv[2], path)
    else:
        print(f"未知命令: {cmd}")
        print(help_text())
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))
