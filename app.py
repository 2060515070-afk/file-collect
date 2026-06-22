"""
文件收集站 - FileCollect
一个现代化的文件收集与管理平台
"""

import os
import json
import uuid
import smtplib
import zipfile
import io
import hashlib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify, redirect,
    url_for, session, send_file, flash
)

try:
    import supabase_client as sb
except Exception:
    sb = None
    print("Warning: supabase_client not available, using local storage")

# ── 配置 ──────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 阿里云 FC 环境下用 /tmp（唯一可写目录），本地用项目目录
IS_FC = os.path.exists('/code')
IS_VERCEL = bool(os.environ.get('VERCEL'))
DATA_DIR = os.environ.get('DATA_DIR', '/tmp' if (IS_FC or IS_VERCEL) else BASE_DIR)

# 确保模板目录在 FC 环境下可找到
TEMPLATE_DIR = '/code/templates' if IS_FC else os.path.join(BASE_DIR, 'templates')
app = Flask(__name__,
            template_folder=TEMPLATE_DIR,
            static_folder=os.path.join(BASE_DIR, 'static'))
app.secret_key = os.environ.get('SECRET_KEY', 'filecollect-secret-' + uuid.uuid4().hex[:8])
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB
app.config['UPLOAD_FOLDER'] = os.path.join(DATA_DIR, 'uploads')

# SMTP 配置 (可通过环境变量覆盖)
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.qq.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '465'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')

# 管理员密码 (可通过环境变量覆盖)
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

# 数据文件路径
DATA_FILE = os.path.join(DATA_DIR, 'data.json')

# 确保目录存在（FC 环境下必须在启动时创建）
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ── 文件类型配置 ──────────────────────────────────────────────────────
FILE_TYPES = {
    'pdf': {'name': 'PDF', 'ext': ['.pdf'], 'icon': '📄', 'color': '#ef4444'},
    'word': {'name': 'Word', 'ext': ['.doc', '.docx'], 'icon': '📝', 'color': '#3b82f6'},
    'excel': {'name': 'Excel', 'ext': ['.xls', '.xlsx', '.csv'], 'icon': '📊', 'color': '#22c55e'},
    'ppt': {'name': 'PPT', 'ext': ['.ppt', '.pptx'], 'icon': '📽️', 'color': '#f97316'},
    'image': {'name': '图片', 'ext': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'], 'icon': '🖼️', 'color': '#8b5cf6'},
    'video': {'name': '视频', 'ext': ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv'], 'icon': '🎬', 'color': '#ec4899'},
    'audio': {'name': '音频', 'ext': ['.mp3', '.wav', '.flac', '.aac', '.ogg'], 'icon': '🎵', 'color': '#14b8a6'},
    'zip': {'name': '压缩包', 'ext': ['.zip', '.rar', '.7z', '.tar', '.gz'], 'icon': '📦', 'color': '#a855f7'},
    'text': {'name': '文本', 'ext': ['.txt', '.md', '.log'], 'icon': '📃', 'color': '#6b7280'},
    'code': {'name': '代码', 'ext': ['.py', '.js', '.html', '.css', '.java', '.cpp', '.c', '.h', '.json', '.xml', '.yaml', '.yml'], 'icon': '💻', 'color': '#06b6d4'},
    'folder': {'name': '文件夹', 'ext': [], 'icon': '📁', 'color': '#eab308'},
    'any': {'name': '任意文件', 'ext': [], 'icon': '📎', 'color': '#64748b'},
}


# ── 数据管理 ──────────────────────────────────────────────────────────
def _sb_available():
    return sb is not None and sb.is_configured()


def load_data():
    # 优先用 Supabase
    if _sb_available():
        collections = sb.get_all_collections()
        if collections is not None:
            return {'collections': collections}
    # 回退到本地文件
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'collections': {}}


def save_data(data):
    # Supabase: 逐个保存
    sb_ok = True
    if _sb_available():
        for cid, col in data.get('collections', {}).items():
            result = sb.save_collection(col)
            if result is None:
                sb_ok = False
    # 同时保存到本地（备份）
    local_ok = False
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        local_ok = True
    except Exception:
        pass  # Vercel 可能无法写文件
    return sb_ok or local_ok


def get_collection(collection_id):
    # 优先用 Supabase
    if _sb_available():
        try:
            result = sb._request('GET', f'collections?id=eq.{collection_id}&select=*')
            if result and len(result) > 0:
                row = result[0]
                return {
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
        except Exception as e:
            print(f'[get_collection] Supabase error: {e}')
    # 回退到本地
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data['collections'].get(collection_id)
    except Exception:
        return None


def update_collection(collection_id, updates):
    data = load_data()
    if collection_id in data['collections']:
        data['collections'][collection_id].update(updates)
        save_data(data)
        return True
    return False


# ── 认证 ──────────────────────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


# ── 邮件发送 ──────────────────────────────────────────────────────────
def send_email(to_email, subject, body, attachment_path=None, attachment_name=None):
    if not SMTP_USER or not SMTP_PASS:
        return False, 'SMTP 未配置，请设置环境变量 SMTP_USER 和 SMTP_PASS'

    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html', 'utf-8'))

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{attachment_name or "files.zip"}"')
            msg.attach(part)

        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.starttls()

        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        return True, '邮件发送成功'
    except Exception as e:
        return False, f'邮件发送失败: {str(e)}'


def create_zip(collection):
    """将所有已提交的文件打包成 ZIP"""
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for person in collection.get('people', []):
            if person.get('submitted') and person.get('files'):
                for file_info in person['files']:
                    arcname = f"{person['name']}/{file_info['original_name']}"
                    # 优先从本地读取
                    file_path = file_info.get('path')
                    if file_path and os.path.exists(file_path):
                        zf.write(file_path, arcname)
                    # 回退：从 Supabase Storage 下载
                    elif file_info.get('storage_path') and _sb_available():
                        data = sb.download_file(file_info['storage_path'])
                        if data:
                            zf.writestr(arcname, data)
    mem_zip.seek(0)
    return mem_zip


def save_zip_to_temp(collection):
    """保存 ZIP 到临时文件"""
    zip_data = create_zip(collection)
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{collection['id']}_pack.zip")
    with open(temp_path, 'wb') as f:
        f.write(zip_data.read())
    return temp_path


def check_and_auto_email(collection_id):
    """检查是否所有人都已提交，如果是则自动发送邮件"""
    collection = get_collection(collection_id)
    if not collection or collection.get('emailed'):
        return

    people = collection.get('people', [])
    if not people:
        return

    all_submitted = all(p.get('submitted', False) for p in people)
    if not all_submitted:
        return

    target_email = collection.get('target_email')
    if not target_email:
        return

    # 打包并发送
    zip_path = save_zip_to_temp(collection)
    submitted_count = sum(1 for p in people if p.get('submitted'))

    html_body = f"""
    <div style="font-family: 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 12px 12px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 24px;">📦 文件收集完成</h1>
        </div>
        <div style="background: #f8fafc; padding: 30px; border: 1px solid #e2e8f0; border-radius: 0 0 12px 12px;">
            <p style="color: #334155; font-size: 16px;">您好，</p>
            <p style="color: #334155;">
                <strong>「{collection['title']}」</strong> 的所有文件已收集完成！
            </p>
            <div style="background: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #22c55e;">
                <p style="margin: 5px 0; color: #475569;">✅ 已收集: <strong>{submitted_count}/{len(people)}</strong> 人</p>
                <p style="margin: 5px 0; color: #475569;">📎 附件: 所有文件已打包为 ZIP</p>
            </div>
            <p style="color: #94a3b8; font-size: 12px; margin-top: 30px;">
                此邮件由文件收集站自动发送
            </p>
        </div>
    </div>
    """

    success, msg = send_email(
        target_email,
        f"📦 文件收集完成 - {collection['title']}",
        html_body,
        zip_path,
        f"{collection['title']}_全部文件.zip"
    )

    if success:
        update_collection(collection_id, {'emailed': True, 'emailed_at': datetime.now().isoformat()})

    # 清理临时 ZIP
    if os.path.exists(zip_path):
        os.remove(zip_path)

    return success


# ── 路由 ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html', file_types=FILE_TYPES)


@app.route('/api/file-types')
def api_file_types():
    return jsonify(FILE_TYPES)


@app.route('/health')
def health():
    import glob
    files = glob.glob('/code/templates/*')
    return jsonify({'status': 'ok', 'template_dir': app.template_folder, 'exists': os.path.exists('/code/templates'), 'files': files, 'data_dir': DATA_DIR, 'cwd': os.getcwd()})


@app.route('/debug/supabase')
def debug_supabase():
    """诊断 Supabase 连接"""
    import urllib.request, urllib.error
    result = {
        'sb_available': _sb_available(),
        'supabase_url': bool(os.environ.get('SUPABASE_URL')),
        'supabase_key_set': bool(os.environ.get('SUPABASE_KEY')),
        'supabase_key_prefix': os.environ.get('SUPABASE_KEY', '')[:20] + '...',
        'is_vercel': IS_VERCEL,
        'data_dir': DATA_DIR,
    }
    # 测试读取
    try:
        cols = sb.get_all_collections() if _sb_available() else None
        result['read_ok'] = cols is not None
        result['read_count'] = len(cols) if cols else 0
    except Exception as e:
        result['read_error'] = str(e)
    # 测试写入 - 先删后插，排除主键冲突
    if _sb_available():
        supabase_url = os.environ.get('SUPABASE_URL')
        supabase_key = os.environ.get('SUPABASE_KEY', '')
        test_id = 'diag_test_001'
        # 先删除旧测试记录
        try:
            del_req = urllib.request.Request(
                f"{supabase_url}/rest/v1/collections?id=eq.{test_id}",
                headers={'apikey': supabase_key, 'Authorization': f'Bearer {supabase_key}'},
                method='DELETE'
            )
            urllib.request.urlopen(del_req, timeout=10)
        except Exception:
            pass
        # 再尝试写入
        test_row = {'id': test_id, 'title': 'diagnostic', 'description': '', 'target_email': '', 'allowed_types': '["any"]', 'people': '[]', 'max_files': 10, 'max_size_mb': 50, 'created_at': '2026-01-01T00:00:00', 'emailed': False}
        headers = {
            'apikey': supabase_key,
            'Authorization': f'Bearer {supabase_key}',
            'Content-Type': 'application/json',
            'Prefer': 'return=representation',
        }
        body = json.dumps(test_row).encode('utf-8')
        req = urllib.request.Request(f"{supabase_url}/rest/v1/collections", data=body, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result['write_ok'] = True
                result['write_status'] = resp.status
        except urllib.error.HTTPError as e:
            result['write_ok'] = False
            result['write_error'] = f'HTTP {e.code}'
            result['write_detail'] = e.read().decode('utf-8', errors='replace')[:500]
        except Exception as e:
            result['write_ok'] = False
            result['write_error'] = f'{type(e).__name__}: {str(e)[:300]}'
    return jsonify(result)


# ── 管理员认证 ────────────────────────────────────────────────────────
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        flash('密码错误', 'error')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('index'))


# ── 管理后台 ──────────────────────────────────────────────────────────
@app.route('/admin')
@admin_required
def admin_dashboard():
    data = load_data()
    collections = sorted(
        data['collections'].values(),
        key=lambda x: x.get('created_at', ''),
        reverse=True
    )
    return render_template('admin_dashboard.html', collections=collections, file_types=FILE_TYPES)


@app.route('/admin/create', methods=['GET', 'POST'])
@admin_required
def admin_create():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        target_email = request.form.get('target_email', '').strip()
        allowed_types = request.form.getlist('file_types')
        people_raw = request.form.get('people', '').strip()
        max_files = int(request.form.get('max_files', 10))
        max_size_mb = int(request.form.get('max_size_mb', 50))

        if not title:
            flash('请输入收集标题', 'error')
            return render_template('admin_create.html', file_types=FILE_TYPES)

        # 解析人员名单
        people = []
        if people_raw:
            for line in people_raw.strip().split('\n'):
                name = line.strip()
                if name:
                    people.append({
                        'id': uuid.uuid4().hex[:8],
                        'name': name,
                        'submitted': False,
                        'files': [],
                        'submitted_at': None
                    })

        if not allowed_types:
            allowed_types = ['any']

        collection_id = uuid.uuid4().hex[:12]
        collection = {
            'id': collection_id,
            'title': title,
            'description': description,
            'target_email': target_email,
            'allowed_types': allowed_types,
            'people': people,
            'max_files': max_files,
            'max_size_mb': max_size_mb,
            'created_at': datetime.now().isoformat(),
            'emailed': False,
            'emailed_at': None,
        }

        data = load_data()
        data['collections'][collection_id] = collection
        save_ok = save_data(data)

        if not save_ok:
            flash('数据保存失败，请检查 Supabase 配置或稍后重试', 'error')
            return render_template('admin_create.html', file_types=FILE_TYPES)

        flash('收集任务创建成功！', 'success')
        return redirect(url_for('admin_collection', collection_id=collection_id))

    return render_template('admin_create.html', file_types=FILE_TYPES)


@app.route('/admin/collection/<collection_id>')
@admin_required
def admin_collection(collection_id):
    collection = get_collection(collection_id)
    if not collection:
        flash('收集任务不存在', 'error')
        return redirect(url_for('admin_dashboard'))

    share_url = request.host_url.rstrip('/') + url_for('submit_page', collection_id=collection_id)
    return render_template('admin_collection.html',
                         collection=collection,
                         share_url=share_url,
                         file_types=FILE_TYPES)


# ── 管理 API ──────────────────────────────────────────────────────────
@app.route('/api/collection/<collection_id>/add-people', methods=['POST'])
@admin_required
def api_add_people(collection_id):
    collection = get_collection(collection_id)
    if not collection:
        return jsonify({'error': '收集任务不存在'}), 404

    names = request.json.get('names', [])
    for name in names:
        name = name.strip()
        if name and not any(p['name'] == name for p in collection['people']):
            collection['people'].append({
                'id': uuid.uuid4().hex[:8],
                'name': name,
                'submitted': False,
                'files': [],
                'submitted_at': None
            })

    update_collection(collection_id, {'people': collection['people']})
    return jsonify({'success': True, 'people': collection['people']})


@app.route('/api/collection/<collection_id>/remove-person/<person_id>', methods=['DELETE'])
@admin_required
def api_remove_person(collection_id, person_id):
    collection = get_collection(collection_id)
    if not collection:
        return jsonify({'error': '收集任务不存在'}), 404

    collection['people'] = [p for p in collection['people'] if p['id'] != person_id]
    update_collection(collection_id, {'people': collection['people']})
    return jsonify({'success': True})


@app.route('/api/collection/<collection_id>/delete', methods=['DELETE'])
@admin_required
def api_delete_collection(collection_id):
    collection = get_collection(collection_id)
    if not collection:
        return jsonify({'error': '收集任务不存在'}), 404

    # 删除上传的文件
    for person in collection.get('people', []):
        for file_info in person.get('files', []):
            # 删除本地文件
            if file_info.get('path') and os.path.exists(file_info['path']):
                os.remove(file_info['path'])
            # 删除 Supabase Storage 文件
            if file_info.get('storage_path') and _sb_available():
                sb.delete_file(file_info['storage_path'])

    # 直接从 Supabase 删除（不再全量读写）
    if _sb_available():
        sb.delete_collection(collection_id)
    else:
        # 本地文件回退
        data = load_data()
        if collection_id in data['collections']:
            del data['collections'][collection_id]
            save_data(data)

    return jsonify({'success': True})


@app.route('/api/collection/<collection_id>/send-email', methods=['POST'])
@admin_required
def api_send_email(collection_id):
    collection = get_collection(collection_id)
    if not collection:
        return jsonify({'error': '收集任务不存在'}), 404

    target_email = request.json.get('email') or collection.get('target_email')
    if not target_email:
        return jsonify({'error': '请指定接收邮箱'}), 400

    # 更新目标邮箱
    update_collection(collection_id, {'target_email': target_email})

    zip_path = save_zip_to_temp(collection)
    people = collection.get('people', [])
    submitted_count = sum(1 for p in people if p.get('submitted'))

    html_body = f"""
    <div style="font-family: 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 12px 12px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 24px;">📦 文件收集 - {collection['title']}</h1>
        </div>
        <div style="background: #f8fafc; padding: 30px; border: 1px solid #e2e8f0; border-radius: 0 0 12px 12px;">
            <p style="color: #334155;">您好，以下是文件收集结果：</p>
            <div style="background: white; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 5px 0; color: #475569;">📋 任务: <strong>{collection['title']}</strong></p>
                <p style="margin: 5px 0; color: #475569;">✅ 已提交: <strong>{submitted_count}/{len(people)}</strong> 人</p>
            </div>
            <p style="color: #94a3b8; font-size: 12px;">此邮件由文件收集站发送</p>
        </div>
    </div>
    """

    success, msg = send_email(
        target_email,
        f"📦 文件收集 - {collection['title']}",
        html_body,
        zip_path,
        f"{collection['title']}_全部文件.zip"
    )

    if os.path.exists(zip_path):
        os.remove(zip_path)

    if success:
        update_collection(collection_id, {'emailed': True, 'emailed_at': datetime.now().isoformat()})
        return jsonify({'success': True, 'message': '邮件发送成功'})
    else:
        return jsonify({'error': msg}), 500


@app.route('/api/collection/<collection_id>/download-zip')
@admin_required
def api_download_zip(collection_id):
    collection = get_collection(collection_id)
    if not collection:
        return jsonify({'error': '收集任务不存在'}), 404

    zip_data = create_zip(collection)
    return send_file(
        zip_data,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"{collection['title']}_全部文件.zip"
    )


@app.route('/api/collection/<collection_id>/reset-person/<person_id>', methods=['POST'])
@admin_required
def api_reset_person(collection_id, person_id):
    """重置某人的提交状态（允许重新提交）"""
    collection = get_collection(collection_id)
    if not collection:
        return jsonify({'error': '收集任务不存在'}), 404

    for person in collection['people']:
        if person['id'] == person_id:
            # 删除已上传的文件
            for file_info in person.get('files', []):
                if file_info.get('path') and os.path.exists(file_info['path']):
                    os.remove(file_info['path'])
            person['submitted'] = False
            person['files'] = []
            person['submitted_at'] = None
            break

    update_collection(collection_id, {
        'people': collection['people'],
        'emailed': False
    })
    return jsonify({'success': True})


# ── 提交页面 ──────────────────────────────────────────────────────────
@app.route('/submit/<collection_id>')
def submit_page(collection_id):
    collection = get_collection(collection_id)
    if not collection:
        return render_template('error.html', message='收集任务不存在或已过期'), 404
    return render_template('submit.html', collection=collection, file_types=FILE_TYPES, hide_admin_link=True)


@app.route('/api/submit/<collection_id>', methods=['POST'])
def api_submit(collection_id):
    collection = get_collection(collection_id)
    if not collection:
        return jsonify({'error': '收集任务不存在'}), 404

    person_id = request.form.get('person_id')
    if not person_id:
        return jsonify({'error': '请选择您的姓名'}), 400

    # 查找人员
    person = None
    person_index = None
    for i, p in enumerate(collection['people']):
        if p['id'] == person_id:
            person = p
            person_index = i
            break

    if not person:
        return jsonify({'error': '未找到您的姓名'}), 400

    if person.get('submitted'):
        return jsonify({'error': '您已提交过文件，如需重新提交请联系管理员'}), 400

    # 获取上传的文件
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': '请选择要上传的文件'}), 400

    # 验证文件类型
    allowed_types = collection.get('allowed_types', ['any'])
    max_files = collection.get('max_files', 10)
    max_size_mb = collection.get('max_size_mb', 50)
    max_size_bytes = max_size_mb * 1024 * 1024

    if len(files) > max_files:
        return jsonify({'error': f'最多只能上传 {max_files} 个文件'}), 400

    # 创建上传目录
    upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], collection_id, person_id)
    os.makedirs(upload_dir, exist_ok=True)

    uploaded_files = []
    for file in files:
        if not file.filename:
            continue

        # 检查文件大小
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)

        if file_size > max_size_bytes:
            return jsonify({'error': f'文件 {file.filename} 超过大小限制 ({max_size_mb}MB)'}), 400

        # 检查文件类型
        if 'any' not in allowed_types and 'folder' not in allowed_types:
            ext = os.path.splitext(file.filename)[1].lower()
            type_allowed = False
            for type_key in allowed_types:
                if type_key in FILE_TYPES:
                    if ext in FILE_TYPES[type_key]['ext'] or type_key == 'any':
                        type_allowed = True
                        break
            if not type_allowed:
                return jsonify({'error': f'文件 {file.filename} 的类型不被允许'}), 400

        # 读取文件内容
        file_data = file.read()
        safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
        storage_path = f"{collection_id}/{person_id}/{safe_name}"

        # 上传到 Supabase Storage（优先）
        storage_ok = False
        if _sb_available():
            content_type = file.content_type or 'application/octet-stream'
            storage_ok = sb.upload_file(file_data, storage_path, content_type)

        # 回退：保存到本地
        local_path = None
        if not storage_ok:
            upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], collection_id, person_id)
            os.makedirs(upload_dir, exist_ok=True)
            local_path = os.path.join(upload_dir, safe_name)
            with open(local_path, 'wb') as f:
                f.write(file_data)

        uploaded_files.append({
            'original_name': file.filename,
            'saved_name': safe_name,
            'storage_path': storage_path if storage_ok else '',
            'path': local_path or '',
            'size': file_size,
            'uploaded_at': datetime.now().isoformat()
        })

    if not uploaded_files:
        return jsonify({'error': '没有有效的文件被上传'}), 400

    # 更新人员状态
    collection['people'][person_index]['submitted'] = True
    collection['people'][person_index]['files'] = uploaded_files
    collection['people'][person_index]['submitted_at'] = datetime.now().isoformat()

    update_collection(collection_id, {
        'people': collection['people'],
        'emailed': False  # 重置邮件状态，因为有新提交
    })

    # 检查是否所有人都提交了
    check_and_auto_email(collection_id)

    return jsonify({
        'success': True,
        'message': '文件提交成功！',
        'files_count': len(uploaded_files)
    })


@app.route('/api/collection/<collection_id>/status')
def api_collection_status(collection_id):
    """公开的状态查询 API（提交页面用）"""
    collection = get_collection(collection_id)
    if not collection:
        return jsonify({'error': '不存在'}), 404

    people = collection.get('people', [])
    return jsonify({
        'total': len(people),
        'submitted': sum(1 for p in people if p.get('submitted')),
        'people': [
            {'name': p['name'], 'submitted': p.get('submitted', False)}
            for p in people
        ]
    })


@app.route('/api/collection/<collection_id>/check-email')
@admin_required
def api_check_email(collection_id):
    """手动检查并触发自动邮件"""
    result = check_and_auto_email(collection_id)
    if result:
        return jsonify({'success': True, 'message': '已自动发送邮件'})
    collection = get_collection(collection_id)
    if collection.get('emailed'):
        return jsonify({'success': True, 'message': '邮件已发送过'})
    return jsonify({'success': False, 'message': '尚未全部提交'})


# ── 错误处理 ──────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    try:
        return render_template('error.html', message='页面不存在'), 404
    except Exception:
        return '<h1>404 - 页面不存在</h1><p><a href="/">返回首页</a></p>', 404


@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': '文件太大'}), 413


@app.errorhandler(500)
def internal_error(e):
    import traceback
    return f'<pre>500 Error:\
{traceback.format_exc()}</pre>', 500


# ── 启动 ──────────────────────────────────────────────────────────────
if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    print()
    print('=' * 50)
    print('  FileCollect - File Collection Platform')
    print('  http://localhost:5000')
    print('  Admin Password: ' + ADMIN_PASSWORD)
    print('=' * 50)
    print()
    app.run(host='0.0.0.0', port=5000, debug=True)

