import base64
import json
import os
import secrets
import sqlite3
import string
import sys
import threading
import time
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    has_app_context,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from openai import OpenAI
from cryptography.fernet import Fernet, InvalidToken
from werkzeug.security import check_password_hash, generate_password_hash

sys.modules.setdefault("app", sys.modules[__name__])


BASE_DIR = Path(__file__).resolve().parent
BASE_PATH = os.getenv("BASE_PATH", "").strip()
if BASE_PATH in {"", "/"}:
    BASE_PATH = ""
else:
    BASE_PATH = "/" + BASE_PATH.strip("/")
GENERATED_DIR = BASE_DIR / "generated"
GENERATED_DIR.mkdir(exist_ok=True)
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE = DATA_DIR / "history.json"
DATABASE_FILE = DATA_DIR / "app.sqlite3"
SECRET_KEY_FILE = DATA_DIR / "secret.key"
FERNET_KEY_FILE = DATA_DIR / "fernet.key"
IMAGE_INSPIRER_DIR = BASE_DIR / "image-inspirer-main"
IMAGE_INSPIRER_DB_DIR = IMAGE_INSPIRER_DIR / "db"
IMAGE_INSPIRER_SOURCE_URL = "https://github.com/wukongnotnull/image-inspirer"

DEFAULTS = {
    "base_url": os.getenv("OPENAI_BASE_URL", "https://ai.wqwlkj.cn"),
    "api_key": os.getenv("OPENAI_API_KEY", ""),
    "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
    "size": "1024x1024",
    "quality": "auto",
    "background": "auto",
    "output_format": "png",
    "n": 1,
    "polish_prompt": False,
}

MODEL_OPTIONS = [
    {"value": "gpt-image-1", "label": "gpt-image-1", "hint": "推荐，通用高质量生图"},
    {"value": "dall-e-3", "label": "dall-e-3", "hint": "擅长海报和指令遵循"},
    {"value": "dall-e-2", "label": "dall-e-2", "hint": "经典模型，兼容性更广"},
    {"value": "__custom__", "label": "自定义模型", "hint": "用于兼容接口的特殊模型名"},
]

IMAGE_MODEL_KEYWORDS = ("image", "dall-e", "sora")

GPT_IMAGE_MODELS = ("gpt-image",)
DALLE3_MODELS = ("dall-e-3",)
DALLE2_MODELS = ("dall-e-2",)

JOB_STATUS_LABELS = {
    "pending": "待生成",
    "running": "生成中",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}

REDEEM_CODE_CHARS = string.ascii_uppercase + string.digits
REDEEM_CODE_TYPES = {
    "single": "单人一次卡",
    "multi": "多人上限卡",
}

INSPIRER_CATEGORIES = [
    {
        "value": "auto",
        "label": "自动识别",
        "directory": "",
        "keywords": (),
    },
    {
        "value": "poster",
        "label": "海报与排版",
        "directory": "海报与排版",
        "keywords": ("海报", "排版", "封面", "campaign", "宣传", "活动", "主视觉"),
    },
    {
        "value": "ui",
        "label": "UI 与界面",
        "directory": "UI与界面",
        "keywords": ("界面", "app", "网页", "ui", "手机", "后台", "仪表盘", "截图", "直播"),
    },
    {
        "value": "infographic",
        "label": "图表与信息可视化",
        "directory": "图表与信息可视化",
        "keywords": ("信息图", "图表", "可视化", "拆解", "图解", "科普", "流程"),
    },
    {
        "value": "illustration",
        "label": "插画与艺术",
        "directory": "插画与艺术",
        "keywords": ("插画", "漫画", "二次元", "动漫", "手绘", "水墨", "水彩", "艺术"),
    },
    {
        "value": "photo",
        "label": "摄影与写实",
        "directory": "摄影与写实",
        "keywords": ("摄影", "写实", "人像", "写真", "自拍", "时尚大片", "照片", "镜头"),
    },
    {
        "value": "ecommerce",
        "label": "商品与电商",
        "directory": "商品与电商",
        "keywords": ("电商", "商品", "产品", "详情页", "淘宝", "广告", "主图"),
    },
    {
        "value": "brand",
        "label": "品牌与标志",
        "directory": "品牌与标志",
        "keywords": ("logo", "品牌", "标志", "vi", "字体", "图标", "商标"),
    },
    {
        "value": "character",
        "label": "人物与角色",
        "directory": "人物与角色",
        "keywords": ("角色", "人物", "卡牌", "动作", "设定", "立绘", "头像"),
    },
    {
        "value": "scene",
        "label": "场景与叙事",
        "directory": "场景与叙事",
        "keywords": ("场景", "叙事", "电影感", "分镜", "故事", "镜头语言"),
    },
    {
        "value": "architecture",
        "label": "建筑与空间",
        "directory": "建筑与空间",
        "keywords": ("建筑", "室内", "空间", "城市", "地标", "房间", "家装"),
    },
    {
        "value": "chinese",
        "label": "历史与古风题材",
        "directory": "历史与古风题材",
        "keywords": ("古风", "历史", "朝代", "国潮", "汉服", "新中式", "传统"),
    },
    {
        "value": "document",
        "label": "文档与出版物",
        "directory": "文档与出版物",
        "keywords": ("文档", "杂志", "菜单", "报纸", "课本", "笔记", "出版物"),
    },
    {
        "value": "creative",
        "label": "其他应用场景",
        "directory": "其他应用场景",
        "keywords": ("创意", "合成", "趣味", "跨界", "搞笑", "混搭", "脑洞"),
    },
]
INSPIRER_CATEGORY_BY_VALUE = {category["value"]: category for category in INSPIRER_CATEGORIES}

WORKER_POLL_SECONDS = 2
WORKER_STALE_RUNNING_SECONDS = 30 * 60
OPENAI_CLIENT_TIMEOUT_SECONDS = 180
WORKER_LOCK = threading.Lock()
WORKER_STARTED = False
WORKER_THREAD = None

def load_secret_key() -> str:
    if SECRET_KEY_FILE.exists():
        value = SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value

    value = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(value, encoding="utf-8")
    return value


def load_fernet() -> Fernet:
    if FERNET_KEY_FILE.exists():
        value = FERNET_KEY_FILE.read_text(encoding="utf-8").strip()
        if value:
            return Fernet(value.encode("utf-8"))

    key = Fernet.generate_key()
    FERNET_KEY_FILE.write_bytes(key)
    return Fernet(key)


def route_path(path: str) -> str:
    return f"{BASE_PATH}{path}" if BASE_PATH else path


app = Flask(__name__, static_url_path=f"{BASE_PATH}/static" if BASE_PATH else "/static")
app.secret_key = load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
FERNET = load_fernet()


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return FERNET.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return FERNET.decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""


def init_database() -> None:
    with sqlite3.connect(DATABASE_FILE) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                credits INTEGER NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0,
                is_disabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                user_id INTEGER,
                job_id INTEGER,
                access_token TEXT,
                visibility TEXT NOT NULL DEFAULT 'public',
                source TEXT NOT NULL DEFAULT 'custom',
                prompt TEXT NOT NULL DEFAULT '',
                effective_prompt TEXT NOT NULL DEFAULT '',
                prompt_polished INTEGER NOT NULL DEFAULT 0,
                model TEXT NOT NULL DEFAULT '',
                revised_prompt TEXT,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS provider_configs (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                base_url TEXT NOT NULL DEFAULT '',
                api_key_encrypted TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT 'gpt-image-1',
                polish_base_url TEXT NOT NULL DEFAULT '',
                polish_api_key_encrypted TEXT NOT NULL DEFAULT '',
                polish_model TEXT NOT NULL DEFAULT '',
                polish_enabled INTEGER NOT NULL DEFAULT 0,
                polish_price INTEGER NOT NULL DEFAULT 0,
                price_per_image INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 0,
                max_concurrent_jobs INTEGER NOT NULL DEFAULT 1,
                per_user_pending_limit INTEGER NOT NULL DEFAULT 3,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recharge_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                notice TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS generation_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                prompt TEXT NOT NULL,
                effective_prompt TEXT NOT NULL DEFAULT '',
                prompt_polished INTEGER NOT NULL DEFAULT 0,
                model TEXT NOT NULL DEFAULT '',
                size TEXT NOT NULL DEFAULT '',
                quality TEXT NOT NULL DEFAULT '',
                background TEXT NOT NULL DEFAULT '',
                output_format TEXT NOT NULL DEFAULT 'png',
                style TEXT NOT NULL DEFAULT '',
                n INTEGER NOT NULL DEFAULT 1,
                cost INTEGER NOT NULL DEFAULT 0,
                publish_to_gallery INTEGER NOT NULL DEFAULT 0,
                error_message TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS custom_generation_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                access_token TEXT NOT NULL UNIQUE,
                user_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                prompt TEXT NOT NULL,
                effective_prompt TEXT NOT NULL DEFAULT '',
                prompt_polished INTEGER NOT NULL DEFAULT 0,
                base_url TEXT NOT NULL DEFAULT '',
                api_key_encrypted TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                size TEXT NOT NULL DEFAULT '',
                quality TEXT NOT NULL DEFAULT '',
                background TEXT NOT NULL DEFAULT '',
                output_format TEXT NOT NULL DEFAULT 'png',
                style TEXT NOT NULL DEFAULT '',
                n INTEGER NOT NULL DEFAULT 1,
                error_message TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS credit_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                job_id INTEGER,
                amount INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (job_id) REFERENCES generation_jobs(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS redeem_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                code_type TEXT NOT NULL DEFAULT 'single',
                credits INTEGER NOT NULL,
                max_uses INTEGER NOT NULL DEFAULT 1,
                used_count INTEGER NOT NULL DEFAULT 0,
                batch_id TEXT NOT NULL DEFAULT '',
                expires_at TEXT,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                deleted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS redeem_code_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                credits INTEGER NOT NULL,
                used_at TEXT NOT NULL,
                FOREIGN KEY (code_id) REFERENCES redeem_codes(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_images_visibility_created
                ON images (visibility, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_images_user_created
                ON images (user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_jobs_status_created
                ON generation_jobs (status, created_at ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_jobs_user_created
                ON generation_jobs (user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_custom_jobs_status_created
                ON custom_generation_jobs (status, created_at ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_custom_jobs_token
                ON custom_generation_jobs (access_token);
            CREATE INDEX IF NOT EXISTS idx_ledger_user_created
                ON credit_ledger (user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_redeem_codes_created
                ON redeem_codes (created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_redeem_uses_code_user
                ON redeem_code_uses (code_id, user_id);
            """
        )
        ensure_column(db, "users", "is_disabled", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(db, "images", "job_id", "INTEGER")
        ensure_column(db, "images", "access_token", "TEXT")
        ensure_column(db, "provider_configs", "polish_base_url", "TEXT NOT NULL DEFAULT ''")
        ensure_column(db, "provider_configs", "polish_api_key_encrypted", "TEXT NOT NULL DEFAULT ''")
        ensure_column(db, "provider_configs", "polish_model", "TEXT NOT NULL DEFAULT ''")
        ensure_column(db, "provider_configs", "polish_enabled", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(db, "provider_configs", "polish_price", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(db, "generation_jobs", "publish_to_gallery", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(db, "redeem_codes", "batch_id", "TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX IF NOT EXISTS idx_images_access_token ON images (access_token)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_redeem_codes_batch ON redeem_codes (batch_id)")
        db.execute(
            """
            INSERT OR IGNORE INTO provider_configs (
                id, base_url, api_key_encrypted, model, price_per_image,
                enabled, max_concurrent_jobs, per_user_pending_limit, updated_at
            ) VALUES (1, '', '', 'gpt-image-1', 1, 0, 1, 3, ?)
            """,
            (now_text(),),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO recharge_settings (id, notice, updated_at)
            VALUES (1, '', ?)
            """,
            (now_text(),),
        )

    migrate_legacy_history()


def ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    rows = db.execute(f"PRAGMA table_info({table})").fetchall()
    if any(row[1] == column for row in rows):
        return
    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migrate_legacy_history() -> None:
    if not HISTORY_FILE.exists():
        return

    try:
        history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return

    if not isinstance(history, list):
        return

    with sqlite3.connect(DATABASE_FILE) as db:
        db.execute("PRAGMA foreign_keys = ON")
        existing_count = db.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        if existing_count:
            return

        for item in reversed(history):
            if not isinstance(item, dict) or not item.get("filename"):
                continue
            db.execute(
                """
                INSERT OR IGNORE INTO images (
                    filename, user_id, visibility, source, prompt, effective_prompt,
                    prompt_polished, model, revised_prompt, created_at, metadata_json
                ) VALUES (?, NULL, 'public', 'legacy', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item.get("filename", "")),
                    str(item.get("prompt", "")),
                    str(item.get("effective_prompt", item.get("prompt", ""))),
                    1 if item.get("prompt_polished") else 0,
                    str(item.get("model", "")),
                    item.get("revised_prompt"),
                    str(item.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))),
                    json.dumps({"legacy_url": item.get("url", "")}, ensure_ascii=False),
                ),
            )


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_FILE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_user_by_id(user_id: int) -> dict | None:
    row = get_db().execute(
        "SELECT id, username, credits, is_admin, is_disabled, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def get_user_with_password(username: str) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT id, username, password_hash, credits, is_admin, is_disabled, created_at FROM users WHERE username = ?",
        (username,),
    ).fetchone()


def users_count() -> int:
    return int(get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0])


def create_user(username: str, password: str) -> dict:
    db = get_db()
    is_admin = 1 if users_count() == 0 else 0
    cursor = db.execute(
        """
        INSERT INTO users (username, password_hash, credits, is_admin, created_at)
        VALUES (?, ?, 0, ?, ?)
        """,
        (username, generate_password_hash(password), is_admin, now_text()),
    )
    db.commit()
    return get_user_by_id(cursor.lastrowid)


def current_user_id() -> int | None:
    user = g.get("current_user")
    return int(user["id"]) if user else None


def get_csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf_token() -> bool:
    expected = session.get("_csrf_token", "")
    submitted = request.form.get("_csrf_token", "")
    return bool(expected and submitted and secrets.compare_digest(expected, submitted))


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not g.get("current_user"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user = g.get("current_user")
        if not user:
            return redirect(url_for("login"))
        if not user.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


@app.before_request
def load_current_user() -> None:
    g.current_user = None
    user_id = session.get("user_id")
    if user_id is not None:
        user = get_user_by_id(int(user_id))
        if user and user.get("is_disabled"):
            session.clear()
            return
        g.current_user = user


@app.context_processor
def inject_template_globals() -> dict:
    return {
        "current_user": g.get("current_user"),
        "csrf_token": get_csrf_token,
    }

def normalize_username(username: str) -> str:
    return "".join(username.strip().split()).lower()


def validate_auth_form(username: str, password: str) -> str | None:
    if len(username) < 3 or len(username) > 32:
        return "用户名长度需要在 3-32 个字符之间。"
    if not username.replace("_", "").replace("-", "").isalnum():
        return "用户名只能包含字母、数字、短横线和下划线。"
    if len(password) < 8:
        return "密码至少需要 8 位。"
    return None


def load_history() -> list[dict]:
    return load_public_images()


def save_history(history: list[dict]) -> None:
    return None


def append_history(entries: list[dict]) -> None:
    for entry in entries:
        create_image_record(entry)


from image_studio.services.pagination import *  # noqa: F401,F403,E402
from image_studio.services.provider import *  # noqa: F401,F403,E402
from image_studio.services.prompts import *  # noqa: F401,F403,E402
from image_studio.services.images import *  # noqa: F401,F403,E402
from image_studio.services.credits import *  # noqa: F401,F403,E402
from image_studio.services.redeem_codes import *  # noqa: F401,F403,E402
from image_studio.services.jobs import *  # noqa: F401,F403,E402
from image_studio.services.admin import *  # noqa: F401,F403,E402
from image_studio.generation_worker import start_generation_worker  # noqa: E402
from image_studio.routes import admin, auth, studio, user  # noqa: F401,E402


init_database()
start_generation_worker()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
