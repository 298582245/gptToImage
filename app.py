import base64
import json
import os
import secrets
import sqlite3
import string
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
WORKER_LOCK = threading.Lock()
WORKER_STARTED = False

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


@app.route(route_path("/login"), methods=["GET", "POST"])
def login():
    if g.get("current_user"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        if not validate_csrf_token():
            abort(400)
        username = normalize_username(request.form.get("username", ""))
        password = request.form.get("password", "")
        user = get_user_with_password(username)
        if user and check_password_hash(user["password_hash"], password):
            if user["is_disabled"]:
                error = "账号已被禁用，请联系管理员。"
                return render_template("auth.html", mode="login", error=error)
            session.clear()
            session["user_id"] = user["id"]
            get_csrf_token()
            return redirect(url_for("index"))
        error = "用户名或密码不正确。"

    return render_template("auth.html", mode="login", error=error)


@app.route(route_path("/register"), methods=["GET", "POST"])
def register():
    if g.get("current_user"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        if not validate_csrf_token():
            abort(400)
        username = normalize_username(request.form.get("username", ""))
        password = request.form.get("password", "")
        error = validate_auth_form(username, password)
        if error is None:
            try:
                user = create_user(username, password)
                session.clear()
                session["user_id"] = user["id"]
                get_csrf_token()
                flash("注册成功，已自动登录。")
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                error = "这个用户名已经被占用。"

    return render_template("auth.html", mode="register", error=error)


@app.post(route_path("/logout"))
def logout():
    if not validate_csrf_token():
        abort(400)
    session.clear()
    return redirect(url_for("index"))


@app.route(route_path("/my/images"))
@login_required
def my_images():
    images = load_user_images(current_user_id())
    return render_template("my_images.html", images=images)


@app.route(route_path("/my/jobs"))
@login_required
def my_jobs():
    selected_job_id = request.args.get("job_id", type=int)
    jobs = load_user_jobs(current_user_id())
    selected_job = None
    selected_images = []
    if selected_job_id:
        row = get_db().execute(
            "SELECT * FROM generation_jobs WHERE id = ? AND user_id = ?",
            (selected_job_id, current_user_id()),
        ).fetchone()
        if row:
            selected_job = job_row_to_dict(row)
            selected_images = load_job_images(selected_job_id)
    return render_template("my_jobs.html", jobs=jobs, selected_job=selected_job, selected_images=selected_images)


@app.get(route_path("/api/my/jobs"))
@login_required
def api_my_jobs():
    jobs = load_user_jobs(current_user_id(), limit=50)
    return jsonify({"ok": True, "jobs": jobs})


@app.route(route_path("/jobs/<access_token>"))
def custom_job_status(access_token: str):
    job = load_custom_job(access_token)
    if not job:
        abort(404)
    images = load_custom_job_images(access_token)
    return render_template("custom_job.html", job=job, images=images)


@app.get(route_path("/api/jobs/<access_token>"))
def api_custom_job(access_token: str):
    job = load_custom_job(access_token)
    if not job:
        abort(404)
    images = load_custom_job_images(access_token)
    return jsonify({"ok": True, "job": job, "image_count": len(images)})


@app.route(route_path("/recharge"), methods=["GET", "POST"])
@login_required
def recharge():
    if request.method == "POST":
        if not validate_csrf_token():
            abort(400)
        try:
            result = redeem_code_for_user(request.form.get("code", ""), current_user_id())
            flash(f"充值成功，到账 {result['credits']} 积分，当前余额 {result['balance']}。")
            return redirect(url_for("recharge"))
        except Exception as exc:  # noqa: BLE001
            flash(f"充值失败：{exc}")

    return render_template(
        "recharge.html",
        settings=get_recharge_settings(),
        recent_uses=load_user_redeem_uses(current_user_id(), limit=10),
    )


def admin_stats(db: sqlite3.Connection) -> dict:
    return {
        "users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "images": db.execute("SELECT COUNT(*) FROM images").fetchone()[0],
        "public_images": db.execute("SELECT COUNT(*) FROM images WHERE visibility = 'public'").fetchone()[0],
        "private_images": db.execute("SELECT COUNT(*) FROM images WHERE visibility = 'private'").fetchone()[0],
        "pending_jobs": db.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM generation_jobs WHERE status = 'pending') +
                (SELECT COUNT(*) FROM custom_generation_jobs WHERE status = 'pending')
            """
        ).fetchone()[0],
        "running_jobs": db.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM generation_jobs WHERE status = 'running') +
                (SELECT COUNT(*) FROM custom_generation_jobs WHERE status = 'running')
            """
        ).fetchone()[0],
    }


def parse_page_params(default_per_page: int, allowed_per_page: tuple[int, ...]) -> tuple[int, int]:
    page = max(1, request.args.get("page", default=1, type=int) or 1)
    per_page = request.args.get("per_page", default=default_per_page, type=int) or default_per_page
    if per_page not in allowed_per_page:
        per_page = default_per_page
    return page, per_page


def pagination_meta(total: int, page: int, per_page: int) -> dict:
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, page), total_pages)
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


def load_users_page(page: int, per_page: int) -> tuple[list[dict], dict]:
    db = get_db()
    total = int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    meta = pagination_meta(total, page, per_page)
    rows = db.execute(
        """
        SELECT id, username, credits, is_admin, is_disabled, created_at
        FROM users
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        (meta["per_page"], (meta["page"] - 1) * meta["per_page"]),
    ).fetchall()
    return [dict(row) for row in rows], meta


def normalize_redeem_code(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch in REDEEM_CODE_CHARS)


def format_redeem_code(value: str) -> str:
    code = normalize_redeem_code(value)
    return "-".join(code[index : index + 4] for index in range(0, len(code), 4))


def parse_redeem_expires_at(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    for date_format in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, date_format).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError("到期时间格式不正确。")


def redeem_code_status(row: dict) -> str:
    if row.get("is_deleted"):
        return "已删除"
    expires_at = row.get("expires_at")
    if expires_at and expires_at < now_text():
        return "已过期"
    if int(row.get("used_count") or 0) >= int(row.get("max_uses") or 0):
        return "已用完"
    return "可使用"


def redeem_code_row_to_dict(row: sqlite3.Row | dict) -> dict:
    item = dict(row)
    item["code_display"] = format_redeem_code(item["code"])
    item["type_label"] = REDEEM_CODE_TYPES.get(item["code_type"], item["code_type"])
    item["expires_label"] = item["expires_at"] or "永久"
    item["status_label"] = redeem_code_status(item)
    return item


def get_recharge_settings() -> dict:
    row = get_db().execute("SELECT * FROM recharge_settings WHERE id = 1").fetchone()
    return dict(row) if row else {"notice": "", "updated_at": ""}


def update_recharge_notice(notice: str) -> None:
    db = get_db()
    db.execute(
        "UPDATE recharge_settings SET notice = ?, updated_at = ? WHERE id = 1",
        (notice.strip(), now_text()),
    )
    db.commit()


def load_redeem_codes_page(page: int, per_page: int) -> tuple[list[dict], dict]:
    db = get_db()
    total = int(db.execute("SELECT COUNT(*) FROM redeem_codes WHERE is_deleted = 0").fetchone()[0])
    meta = pagination_meta(total, page, per_page)
    rows = db.execute(
        """
        SELECT * FROM redeem_codes
        WHERE is_deleted = 0
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (meta["per_page"], (meta["page"] - 1) * meta["per_page"]),
    ).fetchall()
    return [redeem_code_row_to_dict(row) for row in rows], meta


def load_redeem_codes_by_batch(batch_id: str) -> list[dict]:
    if not batch_id:
        return []
    rows = get_db().execute(
        "SELECT * FROM redeem_codes WHERE batch_id = ? ORDER BY id ASC",
        (batch_id,),
    ).fetchall()
    return [redeem_code_row_to_dict(row) for row in rows]


def load_user_redeem_uses(user_id: int, limit: int = 10) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT uses.*, codes.code, codes.code_type
        FROM redeem_code_uses AS uses
        JOIN redeem_codes AS codes ON codes.id = uses.code_id
        WHERE uses.user_id = ?
        ORDER BY uses.used_at DESC, uses.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["code_display"] = format_redeem_code(item["code"])
        item["type_label"] = REDEEM_CODE_TYPES.get(item["code_type"], item["code_type"])
        items.append(item)
    return items


def load_recent_redeem_uses(limit: int = 10) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT uses.*, codes.code, codes.code_type, users.username
        FROM redeem_code_uses AS uses
        JOIN redeem_codes AS codes ON codes.id = uses.code_id
        JOIN users ON users.id = uses.user_id
        ORDER BY uses.used_at DESC, uses.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["code_display"] = format_redeem_code(item["code"])
        item["type_label"] = REDEEM_CODE_TYPES.get(item["code_type"], item["code_type"])
        items.append(item)
    return items


def generate_redeem_code_value() -> str:
    return "".join(secrets.choice(REDEEM_CODE_CHARS) for _ in range(16))


def create_redeem_codes(code_type: str, credits: int, count: int, max_uses: int, expires_at: str | None) -> str:
    if code_type not in REDEEM_CODE_TYPES:
        raise ValueError("请选择正确的卡密类型。")
    if credits <= 0:
        raise ValueError("每张卡密积分必须大于 0。")
    if count <= 0 or count > 200:
        raise ValueError("单次生成数量需要在 1-200 之间。")
    if code_type == "single":
        max_uses = 1
    elif max_uses <= 0:
        raise ValueError("多人卡使用上限必须大于 0。")
    if expires_at and expires_at <= now_text():
        raise ValueError("到期时间必须晚于当前时间。")

    db = get_db()
    batch_id = secrets.token_urlsafe(12)
    try:
        for _ in range(count):
            for _retry in range(20):
                try:
                    db.execute(
                        """
                        INSERT INTO redeem_codes (code, code_type, credits, max_uses, used_count, batch_id, expires_at, created_at)
                        VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                        """,
                        (generate_redeem_code_value(), code_type, credits, max_uses, batch_id, expires_at, now_text()),
                    )
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise ValueError("卡密生成冲突，请重新生成。")
        db.commit()
        return batch_id
    except Exception:
        db.rollback()
        raise


def delete_redeem_codes(code_ids: list[int]) -> int:
    clean_ids = sorted({int(code_id) for code_id in code_ids if int(code_id) > 0})
    if not clean_ids:
        raise ValueError("请选择要删除的卡密。")
    placeholders = ",".join("?" for _ in clean_ids)
    db = get_db()
    cursor = db.execute(
        f"UPDATE redeem_codes SET is_deleted = 1, deleted_at = ? WHERE id IN ({placeholders}) AND is_deleted = 0",
        (now_text(), *clean_ids),
    )
    db.commit()
    return cursor.rowcount


def redeem_code_for_user(raw_code: str, user_id: int) -> dict:
    code = normalize_redeem_code(raw_code)
    if len(code) < 8:
        raise ValueError("请输入正确的卡密。")
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM redeem_codes WHERE code = ?", (code,)).fetchone()
        if not row:
            raise ValueError("卡密不存在。")
        card = dict(row)
        if card["is_deleted"]:
            raise ValueError("卡密已删除。")
        if card["expires_at"] and card["expires_at"] < now_text():
            raise ValueError("卡密已过期。")
        if int(card["used_count"]) >= int(card["max_uses"]):
            raise ValueError("卡密已达到使用上限。")
        used = db.execute(
            "SELECT id FROM redeem_code_uses WHERE code_id = ? AND user_id = ?",
            (card["id"], user_id),
        ).fetchone()
        if used:
            raise ValueError("你已经使用过这张卡密。")

        balance = add_credit_ledger(db, user_id, int(card["credits"]), "卡密充值")
        db.execute(
            """
            INSERT INTO redeem_code_uses (code_id, user_id, credits, used_at)
            VALUES (?, ?, ?, ?)
            """,
            (card["id"], user_id, int(card["credits"]), now_text()),
        )
        db.execute("UPDATE redeem_codes SET used_count = used_count + 1 WHERE id = ?", (card["id"],))
        db.commit()
        return {"credits": int(card["credits"]), "balance": balance}
    except Exception:
        db.rollback()
        raise


def load_recent_images(limit: int = 20) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT images.*, users.username
        FROM images
        LEFT JOIN users ON users.id = images.user_id
        ORDER BY images.created_at DESC, images.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [image_row_to_dict(row) for row in rows]


def load_admin_jobs(limit: int = 80) -> list[dict]:
    db = get_db()
    builtin_rows = db.execute(
        """
        SELECT jobs.*, users.username, COUNT(images.id) AS image_count
        FROM generation_jobs AS jobs
        JOIN users ON users.id = jobs.user_id
        LEFT JOIN images ON images.job_id = jobs.id
        GROUP BY jobs.id
        ORDER BY jobs.created_at DESC, jobs.id DESC
        LIMIT ?
        """
        ,
        (limit,),
    ).fetchall()
    custom_rows = db.execute(
        """
        SELECT jobs.id, jobs.access_token, jobs.user_id, jobs.status, jobs.prompt,
               jobs.effective_prompt, jobs.prompt_polished, jobs.model, jobs.size,
               jobs.quality, jobs.background, jobs.output_format, jobs.style, jobs.n,
               jobs.error_message, jobs.attempts, jobs.created_at, jobs.started_at,
               jobs.completed_at, users.username, COUNT(images.id) AS image_count
        FROM custom_generation_jobs AS jobs
        LEFT JOIN users ON users.id = jobs.user_id
        LEFT JOIN images ON images.access_token = jobs.access_token
        GROUP BY jobs.id
        ORDER BY jobs.created_at DESC, jobs.id DESC
        LIMIT ?
        """
        ,
        (limit,),
    ).fetchall()

    jobs = []
    for row in builtin_rows:
        job = job_row_to_dict(row)
        job.update({"username": row["username"], "mode": "builtin", "mode_label": "内置接口"})
        jobs.append(job)
    for row in custom_rows:
        job = custom_job_row_to_dict(row)
        job.update({"username": row["username"] or "游客", "mode": "custom", "mode_label": "自定义接口"})
        jobs.append(job)
    return sorted(jobs, key=lambda item: (item["created_at"], item["id"]), reverse=True)[:limit]


def load_admin_jobs_page(page: int, per_page: int) -> tuple[list[dict], dict]:
    db = get_db()
    total = int(
        db.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM generation_jobs) +
                (SELECT COUNT(*) FROM custom_generation_jobs)
            """
        ).fetchone()[0]
    )
    meta = pagination_meta(total, page, per_page)
    rows = db.execute(
        """
        SELECT * FROM (
            SELECT jobs.id AS id, NULL AS access_token, jobs.user_id AS user_id,
                   jobs.status AS status, jobs.prompt AS prompt,
                   jobs.effective_prompt AS effective_prompt,
                   jobs.prompt_polished AS prompt_polished, jobs.model AS model,
                   jobs.size AS size, jobs.quality AS quality, jobs.background AS background,
                   jobs.output_format AS output_format, jobs.style AS style, jobs.n AS n,
                   jobs.cost AS cost, jobs.error_message AS error_message,
                   jobs.attempts AS attempts, jobs.created_at AS created_at,
                   jobs.started_at AS started_at, jobs.completed_at AS completed_at,
                   users.username AS username, COUNT(images.id) AS image_count,
                   'builtin' AS mode, '内置接口' AS mode_label
            FROM generation_jobs AS jobs
            JOIN users ON users.id = jobs.user_id
            LEFT JOIN images ON images.job_id = jobs.id
            GROUP BY jobs.id
            UNION ALL
            SELECT jobs.id AS id, jobs.access_token AS access_token, jobs.user_id AS user_id,
                   jobs.status AS status, jobs.prompt AS prompt,
                   jobs.effective_prompt AS effective_prompt,
                   jobs.prompt_polished AS prompt_polished, jobs.model AS model,
                   jobs.size AS size, jobs.quality AS quality, jobs.background AS background,
                   jobs.output_format AS output_format, jobs.style AS style, jobs.n AS n,
                   0 AS cost, jobs.error_message AS error_message,
                   jobs.attempts AS attempts, jobs.created_at AS created_at,
                   jobs.started_at AS started_at, jobs.completed_at AS completed_at,
                   COALESCE(users.username, '游客') AS username, COUNT(images.id) AS image_count,
                   'custom' AS mode, '自定义接口' AS mode_label
            FROM custom_generation_jobs AS jobs
            LEFT JOIN users ON users.id = jobs.user_id
            LEFT JOIN images ON images.access_token = jobs.access_token
            GROUP BY jobs.id
        ) AS merged_jobs
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (meta["per_page"], (meta["page"] - 1) * meta["per_page"]),
    ).fetchall()
    jobs = []
    for row in rows:
        job = dict(row)
        job["status_label"] = JOB_STATUS_LABELS.get(job["status"], job["status"])
        job["prompt_polished"] = bool(job["prompt_polished"])
        jobs.append(job)
    return jobs, meta


@app.route(route_path("/admin"))
@admin_required
def admin_dashboard():
    db = get_db()
    return render_template(
        "admin_dashboard.html",
        active_admin_page="dashboard",
        stats=admin_stats(db),
        recent_images=load_recent_images(limit=5),
        recent_jobs=load_admin_jobs(limit=5),
    )


@app.route(route_path("/admin/provider"))
@admin_required
def admin_provider():
    return render_template(
        "admin_provider.html",
        active_admin_page="provider",
        provider_config=get_provider_config(),
    )


@app.route(route_path("/admin/users"))
@admin_required
def admin_users():
    page, per_page = parse_page_params(10, (10, 20, 50, 100))
    users, pagination = load_users_page(page, per_page)
    return render_template(
        "admin_users.html",
        active_admin_page="users",
        users=users,
        pagination=pagination,
    )


@app.route(route_path("/admin/jobs"))
@admin_required
def admin_jobs():
    page, per_page = parse_page_params(5, (5, 10, 20, 50))
    jobs, pagination = load_admin_jobs_page(page, per_page)
    return render_template(
        "admin_jobs.html",
        active_admin_page="jobs",
        recent_jobs=jobs,
        pagination=pagination,
    )


@app.route(route_path("/admin/images"))
@admin_required
def admin_images():
    return render_template(
        "admin_images.html",
        active_admin_page="images",
        recent_images=load_recent_images(limit=200),
    )


@app.route(route_path("/admin/redeem-codes"))
@admin_required
def admin_redeem_codes():
    page, per_page = parse_page_params(20, (10, 20, 50, 100))
    codes, pagination = load_redeem_codes_page(page, per_page)
    last_batch_id = session.pop("last_redeem_code_batch", "")
    return render_template(
        "admin_redeem_codes.html",
        active_admin_page="redeem_codes",
        codes=codes,
        pagination=pagination,
        settings=get_recharge_settings(),
        recent_uses=load_recent_redeem_uses(limit=10),
        last_created_codes=load_redeem_codes_by_batch(last_batch_id),
        code_types=REDEEM_CODE_TYPES,
    )


@app.post(route_path("/admin/redeem-codes/create"))
@admin_required
def admin_redeem_codes_create():
    if not validate_csrf_token():
        abort(400)
    try:
        batch_id = create_redeem_codes(
            request.form.get("code_type", "single"),
            request.form.get("credits", type=int) or 0,
            request.form.get("count", type=int) or 0,
            request.form.get("max_uses", type=int) or 1,
            parse_redeem_expires_at(request.form.get("expires_at", "")),
        )
        session["last_redeem_code_batch"] = batch_id
        flash("卡密已生成。")
    except Exception as exc:  # noqa: BLE001
        flash(f"生成卡密失败：{exc}")
    return redirect(url_for("admin_redeem_codes"))


@app.post(route_path("/admin/redeem-codes/delete"))
@admin_required
def admin_redeem_codes_delete():
    if not validate_csrf_token():
        abort(400)
    try:
        selected_ids = [int(value) for value in request.form.getlist("code_ids")]
        deleted_count = delete_redeem_codes(selected_ids)
        flash(f"已删除 {deleted_count} 张卡密。")
    except Exception as exc:  # noqa: BLE001
        flash(f"删除卡密失败：{exc}")
    return redirect(url_for("admin_redeem_codes", page=request.args.get("page", 1), per_page=request.args.get("per_page", 20)))


@app.post(route_path("/admin/redeem-codes/notice"))
@admin_required
def admin_recharge_notice_update():
    if not validate_csrf_token():
        abort(400)
    try:
        update_recharge_notice(request.form.get("notice", ""))
        flash("充值公告已保存。")
    except Exception as exc:  # noqa: BLE001
        flash(f"保存充值公告失败：{exc}")
    return redirect(url_for("admin_redeem_codes"))


@app.post(route_path("/admin/users/<int:user_id>/edit"))
@admin_required
def admin_user_edit(user_id: int):
    if not validate_csrf_token():
        abort(400)
    credits = request.form.get("credits", type=int)
    password = request.form.get("password", "")
    try:
        if credits is None:
            raise ValueError("请填写积分。")
        if credits < 0:
            raise ValueError("积分不能小于 0。")
        db = get_db()
        user = db.execute("SELECT id, credits FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise ValueError("用户不存在。")
        if credits != int(user["credits"]):
            add_credit_ledger(db, user_id, credits - int(user["credits"]), "管理员编辑用户积分")
        new_password = password.strip()
        if new_password:
            if len(new_password) < 8:
                raise ValueError("新密码至少需要 8 位。")
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new_password), user_id))
        db.commit()
        flash("用户信息已更新。")
    except Exception as exc:  # noqa: BLE001
        get_db().rollback()
        flash(f"用户更新失败：{exc}")
    return redirect(url_for("admin_users", page=request.args.get("page", 1), per_page=request.args.get("per_page", 10)))


@app.post(route_path("/admin/users/<int:user_id>/toggle"))
@admin_required
def admin_user_toggle(user_id: int):
    if not validate_csrf_token():
        abort(400)
    try:
        current = g.get("current_user")
        if current and current["id"] == user_id:
            raise ValueError("不能禁用当前登录的管理员账号。")
        db = get_db()
        user = db.execute("SELECT id, is_disabled FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise ValueError("用户不存在。")
        new_value = 0 if user["is_disabled"] else 1
        db.execute("UPDATE users SET is_disabled = ? WHERE id = ?", (new_value, user_id))
        db.commit()
        flash("用户状态已更新。")
    except Exception as exc:  # noqa: BLE001
        get_db().rollback()
        flash(f"用户状态更新失败：{exc}")
    return redirect(url_for("admin_users", page=request.args.get("page", 1), per_page=request.args.get("per_page", 10)))


@app.post(route_path("/admin/users/<int:user_id>/delete"))
@admin_required
def admin_user_delete(user_id: int):
    if not validate_csrf_token():
        abort(400)
    try:
        current = g.get("current_user")
        if current and current["id"] == user_id:
            raise ValueError("不能删除当前登录的管理员账号。")
        db = get_db()
        user = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise ValueError("用户不存在。")
        db.execute("UPDATE images SET user_id = NULL WHERE user_id = ?", (user_id,))
        db.execute("UPDATE custom_generation_jobs SET user_id = NULL WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
        flash("用户已删除。")
    except Exception as exc:  # noqa: BLE001
        get_db().rollback()
        flash(f"用户删除失败：{exc}")
    return redirect(url_for("admin_users", page=request.args.get("page", 1), per_page=request.args.get("per_page", 10)))


@app.post(route_path("/admin/provider"))
@admin_required
def admin_provider_update():
    if not validate_csrf_token():
        abort(400)
    try:
        update_provider_config(request.form)
        flash("内置接口配置已保存。")
    except Exception as exc:  # noqa: BLE001
        flash(f"保存失败：{exc}")
    return redirect(url_for("admin_provider"))


@app.post(route_path("/admin/jobs/<int:job_id>/cancel"))
@admin_required
def admin_cancel_job(job_id: int):
    if not validate_csrf_token():
        abort(400)
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        job = db.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
        if not job or job["status"] != "pending":
            db.rollback()
            flash("只能取消待生成任务；生成中的任务会在失败时自动退款。")
            return redirect(url_for("admin_jobs"))

        add_credit_ledger(db, job["user_id"], int(job["cost"]), "管理员取消任务退款", job_id)
        db.execute(
            "UPDATE generation_jobs SET status = 'cancelled', error_message = ?, completed_at = ? WHERE id = ?",
            ("管理员取消", now_text(), job_id),
        )
        db.commit()
        flash("任务已取消并退款。")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        flash(f"取消失败：{exc}")
    return redirect(url_for("admin_jobs"))


def normalize_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if not value:
        return value
    if value.endswith("/v1"):
        return value
    return f"{value}/v1"


def build_client(api_key: str, base_url: str) -> OpenAI:
    kwargs = {"api_key": api_key.strip()}
    if base_url.strip():
        kwargs["base_url"] = normalize_base_url(base_url)
    return OpenAI(**kwargs)


def model_family(model: str) -> str:
    value = (model or "").strip().lower()
    if value.startswith(GPT_IMAGE_MODELS) or "image" in value:
        return "gpt-image"
    if "dall-e-3" in value:
        return "dall-e-3"
    if "dall-e-2" in value:
        return "dall-e-2"
    return "gpt-image"


def build_image_params(form_data: dict) -> dict:
    model = form_data["model"].strip()
    family = model_family(model)
    size = form_data["size"]
    quality = form_data["quality"]
    n = max(1, min(int(form_data["n"]), 10))

    params = {
        "model": model,
        "prompt": form_data["prompt"].strip(),
        "size": size,
        "quality": quality,
        "n": n,
    }

    if family == "gpt-image":
        if size not in {"1024x1024", "1024x1536", "1536x1024", "auto"}:
            params["size"] = "1024x1024"
        if quality not in {"low", "medium", "high", "auto"}:
            params["quality"] = "auto"
        params["background"] = form_data["background"]
        params["output_format"] = form_data["output_format"]
    else:
        params["response_format"] = "b64_json"
        params.pop("quality", None)

    if family == "dall-e-3":
        if size not in {"1024x1024", "1024x1792", "1792x1024"}:
            params["size"] = "1024x1024"
        params["quality"] = "hd" if quality == "hd" else "standard"
        params["style"] = form_data["style"]
        params["n"] = 1

    if family == "dall-e-2":
        if size not in {"256x256", "512x512", "1024x1024"}:
            params["size"] = "1024x1024"

    return params


def resolve_model_name(form_data: dict) -> str:
    selected_model = str(form_data.get("model", "")).strip()
    custom_model = str(form_data.get("custom_model", "")).strip()
    if selected_model == "__custom__":
        return custom_model or DEFAULTS["model"]
    return selected_model or DEFAULTS["model"]


def build_fallback_model_options() -> list[dict]:
    return [dict(option) for option in MODEL_OPTIONS]


def with_custom_option(options: list[dict]) -> list[dict]:
    merged = [dict(option) for option in options if option.get("value") != "__custom__"]
    merged.append(dict(MODEL_OPTIONS[-1]))
    return merged


def infer_model_hint(model_id: str) -> str:
    family = model_family(model_id)
    if family == "dall-e-3":
        return "从接口动态加载，识别为 DALL-E 3 类模型"
    if family == "dall-e-2":
        return "从接口动态加载，识别为 DALL-E 2 类模型"
    return "从接口动态加载，识别为图像生成模型"


def sort_model_options(options: list[dict]) -> list[dict]:
    preferred = {"gpt-image-1": 0, "gpt-image-1.5": 1, "chatgpt-image-latest": 2, "dall-e-3": 3, "dall-e-2": 4}
    return sorted(
        options,
        key=lambda item: (preferred.get(item["value"], 999), item["value"].lower()),
    )


def fetch_remote_model_options(api_key: str, base_url: str) -> tuple[list[dict], str]:
    client = build_client(api_key, base_url)
    response = client.models.list()
    raw_models = list(getattr(response, "data", []) or [])

    dynamic_options = []
    fallback_options = []

    for model in raw_models:
        model_id = getattr(model, "id", "") or ""
        if not model_id:
            continue
        option = {
            "value": model_id,
            "label": model_id,
            "hint": infer_model_hint(model_id),
        }
        fallback_options.append(option)
        lowered = model_id.lower()
        if any(keyword in lowered for keyword in IMAGE_MODEL_KEYWORDS):
            dynamic_options.append(option)

    if dynamic_options:
        return with_custom_option(sort_model_options(dynamic_options)), "已从接口动态加载可疑似用于生图的模型列表。"
    if fallback_options:
        return with_custom_option(sort_model_options(fallback_options)), "接口返回了模型列表，但未识别出生图模型，已展示全部模型。"
    return build_fallback_model_options(), "接口没有返回模型，已使用内置默认模型列表。"


def to_bool(value: str) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def resolve_inspirer_category(prompt: str, category_value: str = "auto") -> dict:
    selected = INSPIRER_CATEGORY_BY_VALUE.get(category_value) or INSPIRER_CATEGORY_BY_VALUE["auto"]
    if selected["value"] != "auto":
        return selected

    lowered_prompt = prompt.lower()
    for category in INSPIRER_CATEGORIES:
        if category["value"] == "auto":
            continue
        if any(keyword.lower() in lowered_prompt for keyword in category["keywords"]):
            return category
    return INSPIRER_CATEGORY_BY_VALUE["creative"]


def extract_inspirer_examples(category: dict, limit: int = 2) -> list[str]:
    prompt_file = IMAGE_INSPIRER_DB_DIR / category["directory"] / "prompt.md"
    if not prompt_file.exists():
        return []
    text = prompt_file.read_text(encoding="utf-8", errors="ignore")
    chunks = [chunk.strip() for chunk in text.split("---") if len(chunk.strip()) > 120]
    examples = []
    for chunk in chunks:
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        content_lines = [line for line in lines if not line.startswith("**来源") and not line.startswith("![")]
        example = " ".join(content_lines)[:360]
        if example:
            examples.append(example)
        if len(examples) >= limit:
            break
    return examples


def build_inspirer_style_hints(examples: list[str]) -> str:
    text = "\n".join(examples)
    candidates = [
        ("电影", "电影感光影"),
        ("海报", "海报级构图"),
        ("留白", "克制留白"),
        ("高级", "高级质感"),
        ("写实", "写实细节"),
        ("插画", "插画表现力"),
        ("国潮", "国潮视觉"),
        ("信息图", "信息层级清晰"),
        ("产品", "产品主体突出"),
        ("品牌", "品牌调性统一"),
        ("光影", "明确光影层次"),
        ("材质", "材质细节丰富"),
        ("色彩", "色彩统一"),
        ("文字", "文字清晰可读"),
        ("8K", "高清细节"),
    ]
    hints = []
    for keyword, hint in candidates:
        if keyword in text and hint not in hints:
            hints.append(hint)
        if len(hints) >= 6:
            break
    return "、".join(hints) if hints else "主体明确、构图清晰、光影完整、风格统一、细节丰富"


def polish_prompt_text(prompt: str, category_value: str = "auto") -> str:
    prompt = prompt.strip()
    if not prompt:
        return prompt
    category = resolve_inspirer_category(prompt, category_value)
    examples = extract_inspirer_examples(category)
    style_hints = build_inspirer_style_hints(examples)

    return (
        f"{prompt}\n\n"
        f"将以上需求优化为“{category['label']}”方向的高质量图像。"
        f"风格参考要点：{style_hints}。"
        "保持主体和核心意图不变，补充清晰构图、主体细节、环境空间、镜头视角、光线方向、色彩关系、材质、景深、画面质感和比例。"
        "如果画面包含文字，要求文字清晰可读、排版稳定、不要乱码；避免多余水印、畸形肢体、过度拥挤、低清晰度和风格漂移。"
    )


def decode_image_payload(item, fallback_format: str) -> tuple[bytes, str]:
    if getattr(item, "b64_json", None):
        image_bytes = base64.b64decode(item.b64_json)
        return image_bytes, fallback_format

    if getattr(item, "url", None):
        raise ValueError("当前程序仅保存 base64 返回结果，请改用支持 b64_json 的模型或参数。")

    raise ValueError("接口返回中没有可用的图片数据。")


def detect_extension(image_bytes: bytes, expected_format: str) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "webp"
    return "jpg" if expected_format == "jpeg" else expected_format


def save_image(image_bytes: bytes, output_format: str) -> str:
    ext = detect_extension(image_bytes, output_format)
    filename = f"{uuid.uuid4().hex}.{ext}"
    output_path = GENERATED_DIR / filename
    output_path.write_bytes(image_bytes)
    return filename


def image_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "url": url_for("generated_file", filename=row["filename"]),
        "filename": row["filename"],
        "access_token": row["access_token"] if "access_token" in row.keys() else None,
        "revised_prompt": row["revised_prompt"],
        "prompt": row["prompt"],
        "effective_prompt": row["effective_prompt"],
        "prompt_polished": bool(row["prompt_polished"]),
        "model": row["model"],
        "created_at": row["created_at"],
        "visibility": row["visibility"],
        "source": row["source"],
        "user_id": row["user_id"],
        "username": row["username"] if "username" in row.keys() else None,
    }


def create_image_record(entry: dict, commit: bool = True, db: sqlite3.Connection | None = None) -> dict:
    connection = db or get_db()
    connection.execute(
        """
        INSERT INTO images (
            filename, user_id, job_id, access_token, visibility, source, prompt, effective_prompt,
            prompt_polished, model, revised_prompt, created_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry["filename"],
            entry.get("user_id"),
            entry.get("job_id"),
            entry.get("access_token"),
            entry.get("visibility", "public"),
            entry.get("source", "custom"),
            entry.get("prompt", ""),
            entry.get("effective_prompt", ""),
            1 if entry.get("prompt_polished") else 0,
            entry.get("model", ""),
            entry.get("revised_prompt"),
            entry.get("created_at", now_text()),
            json.dumps(entry.get("metadata", {}), ensure_ascii=False),
        ),
    )
    if commit:
        connection.commit()
    return entry


def load_public_images(limit: int = 120) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT images.*, users.username
        FROM images
        LEFT JOIN users ON users.id = images.user_id
        WHERE images.visibility = 'public'
        ORDER BY images.created_at DESC, images.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [image_row_to_dict(row) for row in rows]


def load_user_images(user_id: int, limit: int = 120) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT images.*, users.username
        FROM images
        LEFT JOIN users ON users.id = images.user_id
        WHERE images.user_id = ?
        ORDER BY images.created_at DESC, images.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [image_row_to_dict(row) for row in rows]


def get_provider_config(include_secret: bool = False, db: sqlite3.Connection | None = None) -> dict:
    connection = db or get_db()
    row = connection.execute("SELECT * FROM provider_configs WHERE id = 1").fetchone()
    config = dict(row) if row else {}
    api_key_encrypted = config.pop("api_key_encrypted", "")
    config["has_api_key"] = bool(api_key_encrypted)
    config["api_key_masked"] = "已设置" if api_key_encrypted else "未设置"
    if include_secret:
        config["api_key"] = decrypt_secret(api_key_encrypted)
    return config


def update_provider_config(form_data) -> None:
    keep_existing_key = form_data.get("keep_existing_key") == "on"
    api_key = form_data.get("api_key", "").strip()
    current = get_provider_config(db=get_db())
    encrypted_key = None
    if api_key:
        encrypted_key = encrypt_secret(api_key)
    elif keep_existing_key and current.get("has_api_key"):
        row = get_db().execute("SELECT api_key_encrypted FROM provider_configs WHERE id = 1").fetchone()
        encrypted_key = row["api_key_encrypted"]
    else:
        encrypted_key = ""

    max_concurrent_jobs = max(1, min(int(form_data.get("max_concurrent_jobs", 1) or 1), 5))
    per_user_pending_limit = max(1, min(int(form_data.get("per_user_pending_limit", 3) or 3), 20))
    price_per_image = max(0, int(form_data.get("price_per_image", 1) or 0))

    get_db().execute(
        """
        UPDATE provider_configs
        SET base_url = ?, api_key_encrypted = ?, model = ?, price_per_image = ?,
            enabled = ?, max_concurrent_jobs = ?, per_user_pending_limit = ?, updated_at = ?
        WHERE id = 1
        """,
        (
            form_data.get("base_url", "").strip(),
            encrypted_key,
            form_data.get("model", "gpt-image-1").strip() or "gpt-image-1",
            price_per_image,
            1 if form_data.get("enabled") == "on" else 0,
            max_concurrent_jobs,
            per_user_pending_limit,
            now_text(),
        ),
    )
    get_db().commit()


def add_credit_ledger(db: sqlite3.Connection, user_id: int, amount: int, reason: str, job_id: int | None = None) -> int:
    user = db.execute("SELECT credits FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        raise ValueError("用户不存在。")
    balance_after = int(user["credits"]) + amount
    if balance_after < 0:
        raise ValueError("积分不足。")
    db.execute("UPDATE users SET credits = ? WHERE id = ?", (balance_after, user_id))
    db.execute(
        """
        INSERT INTO credit_ledger (user_id, job_id, amount, balance_after, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, job_id, amount, balance_after, reason, now_text()),
    )
    return balance_after


def user_active_jobs_count(db: sqlite3.Connection, user_id: int) -> int:
    return int(
        db.execute(
            "SELECT COUNT(*) FROM generation_jobs WHERE user_id = ? AND status IN ('pending', 'running')",
            (user_id,),
        ).fetchone()[0]
    )


def create_builtin_job(form_values: dict) -> int:
    user_id = current_user_id()
    if user_id is None:
        raise ValueError("请先登录后再使用内置接口。")

    db = get_db()
    config = get_provider_config(db=db)
    if not config.get("enabled") or not config.get("has_api_key") or not config.get("base_url"):
        raise ValueError("内置接口暂未启用，请联系管理员配置。")
    if user_active_jobs_count(db, user_id) >= int(config.get("per_user_pending_limit", 3)):
        raise ValueError("你当前排队或生成中的任务太多，请稍后再提交。")

    requested_n = max(1, min(int(form_values["n"]), 10))
    cost = int(config.get("price_per_image", 1)) * requested_n
    original_prompt = form_values["prompt"]
    effective_prompt = polish_prompt_text(original_prompt, form_values.get("polish_category", "auto")) if form_values["polish_prompt"] else original_prompt

    try:
        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute(
            """
            INSERT INTO generation_jobs (
                user_id, status, prompt, effective_prompt, prompt_polished, model,
                size, quality, background, output_format, style, n, cost, created_at
            ) VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                original_prompt,
                effective_prompt,
                1 if form_values["polish_prompt"] else 0,
                config.get("model") or DEFAULTS["model"],
                form_values["size"],
                form_values["quality"],
                form_values["background"],
                form_values["output_format"],
                form_values["style"],
                requested_n,
                cost,
                now_text(),
            ),
        )
        job_id = cursor.lastrowid
        add_credit_ledger(db, user_id, -cost, "内置接口生成预扣", job_id)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return job_id


def create_custom_job(form_values: dict) -> str:
    effective_api_key = form_values["api_key"] or DEFAULTS["api_key"]
    if not effective_api_key:
        raise ValueError("请先填写 API Key。")
    if form_values["model_choice"] == "__custom__" and not form_values["custom_model"]:
        raise ValueError("选择自定义模型时，请填写模型名称。")

    original_prompt = form_values["prompt"]
    effective_prompt = polish_prompt_text(original_prompt, form_values.get("polish_category", "auto")) if form_values["polish_prompt"] else original_prompt
    resolved_model = resolve_model_name(
        {
            "model": form_values["model_choice"],
            "custom_model": form_values.get("custom_model", ""),
        }
    )
    requested_n = max(1, min(int(form_values["n"]), 10))
    access_token = secrets.token_urlsafe(32)

    db = get_db()
    db.execute(
        """
        INSERT INTO custom_generation_jobs (
            access_token, user_id, status, prompt, effective_prompt, prompt_polished,
            base_url, api_key_encrypted, model, size, quality, background,
            output_format, style, n, created_at
        ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            access_token,
            current_user_id(),
            original_prompt,
            effective_prompt,
            1 if form_values["polish_prompt"] else 0,
            form_values["base_url"],
            encrypt_secret(effective_api_key),
            resolved_model,
            form_values["size"],
            form_values["quality"],
            form_values["background"],
            form_values["output_format"],
            form_values["style"],
            requested_n,
            now_text(),
        ),
    )
    db.commit()
    return access_token


def load_user_jobs(user_id: int, limit: int = 120) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT jobs.*, COUNT(images.id) AS image_count
        FROM generation_jobs AS jobs
        LEFT JOIN images ON images.job_id = jobs.id
        WHERE jobs.user_id = ?
        GROUP BY jobs.id
        ORDER BY jobs.created_at DESC, jobs.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [job_row_to_dict(row) for row in rows]


def load_job_images(job_id: int) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT images.*, users.username
        FROM images
        LEFT JOIN users ON users.id = images.user_id
        WHERE images.job_id = ?
        ORDER BY images.created_at ASC, images.id ASC
        """,
        (job_id,),
    ).fetchall()
    return [image_row_to_dict(row) for row in rows]


def load_custom_job(access_token: str, db: sqlite3.Connection | None = None) -> dict | None:
    connection = db or get_db()
    row = connection.execute(
        "SELECT * FROM custom_generation_jobs WHERE access_token = ?",
        (access_token,),
    ).fetchone()
    return custom_job_row_to_dict(row) if row else None


def load_custom_job_images(access_token: str) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT images.*, users.username
        FROM images
        LEFT JOIN users ON users.id = images.user_id
        WHERE images.access_token = ?
        ORDER BY images.created_at ASC, images.id ASC
        """,
        (access_token,),
    ).fetchall()
    return [image_row_to_dict(row) for row in rows]


def job_row_to_dict(row: sqlite3.Row) -> dict:
    job = dict(row)
    job["status_label"] = JOB_STATUS_LABELS.get(job["status"], job["status"])
    job["prompt_polished"] = bool(job["prompt_polished"])
    return job


def custom_job_row_to_dict(row: sqlite3.Row) -> dict:
    job = dict(row)
    job.pop("api_key_encrypted", None)
    job["status_label"] = JOB_STATUS_LABELS.get(job["status"], job["status"])
    job["prompt_polished"] = bool(job["prompt_polished"])
    return job


def running_jobs_count(db: sqlite3.Connection) -> int:
    builtin_running = int(db.execute("SELECT COUNT(*) FROM generation_jobs WHERE status = 'running'").fetchone()[0])
    custom_running = int(db.execute("SELECT COUNT(*) FROM custom_generation_jobs WHERE status = 'running'").fetchone()[0])
    return builtin_running + custom_running


def claim_next_job(db: sqlite3.Connection) -> dict | None:
    config = get_provider_config(include_secret=True, db=db)
    max_running = max(1, int(config.get("max_concurrent_jobs", 1) or 1))
    db.execute("BEGIN IMMEDIATE")
    try:
        if running_jobs_count(db) >= max_running:
            db.rollback()
            return None

        row = db.execute(
            """
            SELECT * FROM generation_jobs
            WHERE status = 'pending'
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            db.rollback()
            return None
        db.execute(
            "UPDATE generation_jobs SET status = 'running', started_at = ?, attempts = attempts + 1 WHERE id = ?",
            (now_text(), row["id"]),
        )
        db.commit()
        job = dict(row)
        job["status"] = "running"
        return job
    except Exception:
        db.rollback()
        raise


def refund_job(db: sqlite3.Connection, job: dict, error_message: str) -> None:
    db.execute("BEGIN IMMEDIATE")
    try:
        current = db.execute("SELECT status FROM generation_jobs WHERE id = ?", (job["id"],)).fetchone()
        if current and current["status"] == "running":
            add_credit_ledger(db, job["user_id"], int(job["cost"]), "内置接口生成失败退款", job["id"])
            db.execute(
                "UPDATE generation_jobs SET status = 'failed', error_message = ?, completed_at = ? WHERE id = ?",
                (error_message[:500], now_text(), job["id"]),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise


def complete_job(db: sqlite3.Connection, job: dict, image_entries: list[dict]) -> None:
    db.execute("BEGIN IMMEDIATE")
    try:
        current = db.execute("SELECT status FROM generation_jobs WHERE id = ?", (job["id"],)).fetchone()
        if not current or current["status"] != "running":
            db.rollback()
            return

        for entry in image_entries:
            create_image_record(entry, commit=False, db=db)
        db.execute(
            "UPDATE generation_jobs SET status = 'completed', completed_at = ? WHERE id = ?",
            (now_text(), job["id"]),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def claim_next_custom_job(db: sqlite3.Connection) -> dict | None:
    config = get_provider_config(db=db)
    max_running = max(1, int(config.get("max_concurrent_jobs", 1) or 1))
    db.execute("BEGIN IMMEDIATE")
    try:
        if running_jobs_count(db) >= max_running:
            db.rollback()
            return None

        row = db.execute(
            """
            SELECT * FROM custom_generation_jobs
            WHERE status = 'pending'
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            db.rollback()
            return None
        db.execute(
            "UPDATE custom_generation_jobs SET status = 'running', started_at = ?, attempts = attempts + 1 WHERE id = ?",
            (now_text(), row["id"]),
        )
        db.commit()
        job = dict(row)
        job["status"] = "running"
        return job
    except Exception:
        db.rollback()
        raise


def fail_custom_job(db: sqlite3.Connection, job: dict, error_message: str) -> None:
    db.execute("BEGIN IMMEDIATE")
    try:
        current = db.execute("SELECT status FROM custom_generation_jobs WHERE id = ?", (job["id"],)).fetchone()
        if current and current["status"] == "running":
            db.execute(
                """
                UPDATE custom_generation_jobs
                SET status = 'failed', error_message = ?, api_key_encrypted = '', completed_at = ?
                WHERE id = ?
                """,
                (error_message[:500], now_text(), job["id"]),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise


def complete_custom_job(db: sqlite3.Connection, job: dict, image_entries: list[dict]) -> None:
    db.execute("BEGIN IMMEDIATE")
    try:
        current = db.execute("SELECT status FROM custom_generation_jobs WHERE id = ?", (job["id"],)).fetchone()
        if not current or current["status"] != "running":
            db.rollback()
            return

        for entry in image_entries:
            create_image_record(entry, commit=False, db=db)
        db.execute(
            """
            UPDATE custom_generation_jobs
            SET status = 'completed', api_key_encrypted = '', completed_at = ?
            WHERE id = ?
            """,
            (now_text(), job["id"]),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def open_worker_db() -> sqlite3.Connection:
    db = sqlite3.connect(DATABASE_FILE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def build_job_image_params(job: dict) -> dict:
    return build_image_params(
        {
            "model": job["model"],
            "prompt": job["effective_prompt"],
            "size": job["size"],
            "quality": job["quality"],
            "background": job["background"],
            "output_format": job["output_format"],
            "style": job["style"],
            "n": job["n"],
        }
    )


def process_custom_generation_job(job: dict) -> None:
    if not has_app_context():
        with app.app_context():
            process_custom_generation_job(job)
        return

    db = open_worker_db()
    try:
        api_key = decrypt_secret(job.get("api_key_encrypted", ""))
        if not api_key:
            raise ValueError("自定义接口密钥无法读取，请重新提交任务。")

        client = build_client(api_key, job["base_url"])
        request_payload = build_job_image_params(job)
        response = client.images.generate(**request_payload)
        output_format = request_payload.get("output_format", "png")
        image_entries = []
        for item in response.data:
            image_bytes, detected_format = decode_image_payload(item, output_format)
            filename = save_image(image_bytes, detected_format)
            image_entries.append(
                {
                    "filename": filename,
                    "user_id": job.get("user_id"),
                    "access_token": job["access_token"],
                    "visibility": "public",
                    "source": "custom",
                    "revised_prompt": getattr(item, "revised_prompt", None),
                    "prompt": job["prompt"],
                    "effective_prompt": job["effective_prompt"],
                    "prompt_polished": bool(job["prompt_polished"]),
                    "model": request_payload["model"],
                    "created_at": now_text(),
                    "metadata": {"custom_job_id": job["id"]},
                }
            )
        complete_custom_job(db, job, image_entries)
    except Exception as exc:  # noqa: BLE001
        fail_custom_job(db, job, str(exc))
    finally:
        db.close()


def process_generation_job(job: dict) -> None:
    if not has_app_context():
        with app.app_context():
            process_generation_job(job)
        return

    db = open_worker_db()
    try:
        config = get_provider_config(include_secret=True, db=db)
        if not config.get("enabled") or not config.get("api_key") or not config.get("base_url"):
            raise ValueError("内置接口未启用或配置不完整。")

        client = build_client(config["api_key"], config["base_url"])
        request_payload = build_job_image_params(job)
        response = client.images.generate(**request_payload)
        output_format = request_payload.get("output_format", "png")
        image_entries = []
        for item in response.data:
            image_bytes, detected_format = decode_image_payload(item, output_format)
            filename = save_image(image_bytes, detected_format)
            image_entries.append(
                {
                    "filename": filename,
                    "user_id": job["user_id"],
                    "job_id": job["id"],
                    "visibility": "private",
                    "source": "builtin",
                    "revised_prompt": getattr(item, "revised_prompt", None),
                    "prompt": job["prompt"],
                    "effective_prompt": job["effective_prompt"],
                    "prompt_polished": bool(job["prompt_polished"]),
                    "model": request_payload["model"],
                    "created_at": now_text(),
                    "metadata": {"cost": job["cost"]},
                }
            )
        complete_job(db, job, image_entries)
    except Exception as exc:  # noqa: BLE001
        error_message = str(exc)
        try:
            refund_job(db, job, error_message)
        except Exception as refund_exc:  # noqa: BLE001
            try:
                db.rollback()
                db.execute(
                    "UPDATE generation_jobs SET status = 'failed', error_message = ?, completed_at = ? WHERE id = ?",
                    (f"{error_message}；退款失败：{refund_exc}"[:500], now_text(), job["id"]),
                )
                db.commit()
            except Exception:
                db.rollback()
    finally:
        db.close()


def generation_worker_loop() -> None:
    with app.app_context():
        while True:
            db = open_worker_db()
            try:
                job = claim_next_job(db)
                custom_job = None if job else claim_next_custom_job(db)
            except Exception:
                job = None
                custom_job = None
            finally:
                db.close()

            if job:
                process_generation_job(job)
                continue
            if custom_job:
                process_custom_generation_job(custom_job)
                continue
            time.sleep(WORKER_POLL_SECONDS)


def start_generation_worker() -> None:
    global WORKER_STARTED
    with WORKER_LOCK:
        if WORKER_STARTED:
            return
        thread = threading.Thread(target=generation_worker_loop, name="generation-worker", daemon=True)
        thread.start()
        WORKER_STARTED = True


def load_history() -> list[dict]:
    return load_public_images()


def save_history(history: list[dict]) -> None:
    return None


def append_history(entries: list[dict]) -> None:
    for entry in entries:
        create_image_record(entry)


@app.route(f"{BASE_PATH}/" if BASE_PATH else "/", methods=["GET", "POST"])
def index():
    form_values = {
        "base_url": DEFAULTS["base_url"],
        "api_key": "",
        "model": DEFAULTS["model"],
        "model_choice": DEFAULTS["model"],
        "custom_model": "",
        "prompt": "",
        "size": DEFAULTS["size"],
        "quality": DEFAULTS["quality"],
        "background": DEFAULTS["background"],
        "output_format": DEFAULTS["output_format"],
        "style": "vivid",
        "n": DEFAULTS["n"],
        "polish_prompt": DEFAULTS["polish_prompt"],
        "polish_category": "auto",
        "generation_mode": "custom",
    }
    images = []
    history_items = []
    error = None
    request_payload = None
    model_options = build_fallback_model_options()
    model_status = "当前显示的是内置默认模型列表。"

    if request.method == "POST":
        if not validate_csrf_token():
            abort(400)

        for key in form_values:
            if key == "polish_prompt":
                form_values[key] = to_bool(request.form.get(key, ""))
                continue
            if key == "polish_category":
                value = request.form.get(key, "auto").strip() or "auto"
                form_values[key] = value if value in INSPIRER_CATEGORY_BY_VALUE else "auto"
                continue
            if key == "model_choice":
                form_values[key] = request.form.get("model", "").strip() or form_values[key]
                continue
            if key == "model":
                continue
            if key in request.form:
                form_values[key] = request.form.get(key, "").strip() or form_values[key]

        if form_values["model_choice"] == "__custom__":
            form_values["custom_model"] = request.form.get("custom_model", "").strip()

        try:
            if not form_values["prompt"]:
                raise ValueError("请输入提示词。")

            if form_values["generation_mode"] == "builtin":
                job_id = create_builtin_job(form_values)
                flash("内置接口任务已提交，请在任务列表查看生成进度。")
                return redirect(url_for("my_jobs", job_id=job_id))

            access_token = create_custom_job(form_values)
            flash("任务已提交，生成完成后会自动显示结果。")
            return redirect(url_for("custom_job_status", access_token=access_token))
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

    history_items = load_history()

    return render_template(
        "index.html",
        base_path=BASE_PATH,
        form_values=form_values,
        images=images,
        history_items=history_items,
        error=error,
        request_payload=request_payload,
        model_options=model_options,
        model_status=model_status,
        provider_config=get_provider_config(),
        inspirer_categories=INSPIRER_CATEGORIES,
        inspirer_source_url=IMAGE_INSPIRER_SOURCE_URL,
    )


@app.post(f"{BASE_PATH}/api/models" if BASE_PATH else "/api/models")
def api_models():
    payload = request.get_json(silent=True) or {}
    base_url = str(payload.get("base_url", "")).strip() or DEFAULTS["base_url"]
    api_key = str(payload.get("api_key", "")).strip() or DEFAULTS["api_key"]
    current_model = str(payload.get("current_model", "")).strip()

    if not api_key:
        return jsonify({"ok": False, "error": "请先填写 API Key。"}), 400

    try:
        options, status = fetch_remote_model_options(api_key, base_url)
        selected_model = next(
            (option["value"] for option in options if option["value"] == current_model),
            next(
                (option["value"] for option in options if option["value"] == DEFAULTS["model"]),
                options[0]["value"] if options else DEFAULTS["model"],
            ),
        )
        return jsonify(
            {
                "ok": True,
                "models": options,
                "status": status,
                "selected_model": selected_model,
            }
        )
    except Exception as exc:  # noqa: BLE001
        fallback_options = build_fallback_model_options()
        selected_model = next(
            (option["value"] for option in fallback_options if option["value"] == current_model),
            DEFAULTS["model"],
        )
        return jsonify(
            {
                "ok": False,
                "error": f"加载模型失败：{exc}",
                "models": fallback_options,
                "status": "加载失败，已回退到内置默认模型列表。",
                "selected_model": selected_model,
            }
        ), 500


@app.route(f"{BASE_PATH}/generated/<path:filename>" if BASE_PATH else "/generated/<path:filename>")
def generated_file(filename: str):
    row = get_db().execute(
        "SELECT id, filename, user_id, visibility FROM images WHERE filename = ?",
        (filename,),
    ).fetchone()
    if row and row["visibility"] != "public":
        user = g.get("current_user")
        if not user or (not user.get("is_admin") and user["id"] != row["user_id"]):
            abort(404)
    return send_from_directory(GENERATED_DIR, filename)


init_database()
start_generation_worker()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
