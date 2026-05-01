import base64
import binascii
import json
import os
import secrets
import sqlite3
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
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                user_id INTEGER,
                job_id INTEGER,
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

            CREATE INDEX IF NOT EXISTS idx_images_visibility_created
                ON images (visibility, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_images_user_created
                ON images (user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_jobs_status_created
                ON generation_jobs (status, created_at ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_jobs_user_created
                ON generation_jobs (user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_ledger_user_created
                ON credit_ledger (user_id, created_at DESC, id DESC);
            """
        )
        ensure_column(db, "images", "job_id", "INTEGER")
        db.execute(
            """
            INSERT OR IGNORE INTO provider_configs (
                id, base_url, api_key_encrypted, model, price_per_image,
                enabled, max_concurrent_jobs, per_user_pending_limit, updated_at
            ) VALUES (1, '', '', 'gpt-image-1', 1, 0, 1, 3, ?)
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
        "SELECT id, username, credits, is_admin, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def get_user_with_password(username: str) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT id, username, password_hash, credits, is_admin, created_at FROM users WHERE username = ?",
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
        g.current_user = get_user_by_id(int(user_id))


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


@app.route(route_path("/admin"))
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        "users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "images": db.execute("SELECT COUNT(*) FROM images").fetchone()[0],
        "public_images": db.execute("SELECT COUNT(*) FROM images WHERE visibility = 'public'").fetchone()[0],
        "private_images": db.execute("SELECT COUNT(*) FROM images WHERE visibility = 'private'").fetchone()[0],
        "pending_jobs": db.execute("SELECT COUNT(*) FROM generation_jobs WHERE status = 'pending'").fetchone()[0],
        "running_jobs": db.execute("SELECT COUNT(*) FROM generation_jobs WHERE status = 'running'").fetchone()[0],
    }
    recent_users = db.execute(
        "SELECT id, username, credits, is_admin, created_at FROM users ORDER BY id DESC LIMIT 20"
    ).fetchall()
    recent_images = db.execute(
        """
        SELECT images.*, users.username
        FROM images
        LEFT JOIN users ON users.id = images.user_id
        ORDER BY images.created_at DESC, images.id DESC
        LIMIT 20
        """
    ).fetchall()
    recent_jobs = db.execute(
        """
        SELECT jobs.*, users.username
        FROM generation_jobs AS jobs
        JOIN users ON users.id = jobs.user_id
        ORDER BY jobs.created_at DESC, jobs.id DESC
        LIMIT 20
        """
    ).fetchall()
    return render_template(
        "admin.html",
        stats=stats,
        provider_config=get_provider_config(),
        recent_users=[dict(row) for row in recent_users],
        recent_images=[image_row_to_dict(row) for row in recent_images],
        recent_jobs=[job_row_to_dict(row) | {"username": row["username"]} for row in recent_jobs],
    )


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
    return redirect(url_for("admin_dashboard"))


@app.post(route_path("/admin/credits"))
@admin_required
def admin_credits_update():
    if not validate_csrf_token():
        abort(400)
    user_id = request.form.get("user_id", type=int)
    amount = request.form.get("amount", type=int)
    reason = request.form.get("reason", "管理员调整积分").strip()
    try:
        if user_id is None or amount is None:
            raise ValueError("请选择用户并填写积分数量。")
        admin_adjust_credits(user_id, amount, reason)
        flash("积分已调整。")
    except Exception as exc:  # noqa: BLE001
        flash(f"积分调整失败：{exc}")
    return redirect(url_for("admin_dashboard"))


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
            return redirect(url_for("admin_dashboard"))

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
    return redirect(url_for("admin_dashboard"))


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


def polish_prompt_text(prompt: str) -> str:
    prompt = prompt.strip()
    if not prompt:
        return prompt
    suffix = (
        "。请在不改变主体和核心意图的前提下，补充清晰的构图描述、主体细节、光线、色彩、"
        "材质、景深与画面质感，让结果更适合高质量图像生成。"
    )
    return f"{prompt}{suffix}"


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


def create_image_record(entry: dict, commit: bool = True) -> dict:
    db = get_db()
    db.execute(
        """
        INSERT INTO images (
            filename, user_id, job_id, visibility, source, prompt, effective_prompt,
            prompt_polished, model, revised_prompt, created_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry["filename"],
            entry.get("user_id"),
            entry.get("job_id"),
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
        db.commit()
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


def admin_adjust_credits(user_id: int, amount: int, reason: str) -> None:
    db = get_db()
    add_credit_ledger(db, user_id, amount, reason or "管理员调整积分")
    db.commit()


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
    effective_prompt = polish_prompt_text(original_prompt) if form_values["polish_prompt"] else original_prompt

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


def job_row_to_dict(row: sqlite3.Row) -> dict:
    job = dict(row)
    job["status_label"] = JOB_STATUS_LABELS.get(job["status"], job["status"])
    job["prompt_polished"] = bool(job["prompt_polished"])
    return job


def running_jobs_count(db: sqlite3.Connection) -> int:
    return int(db.execute("SELECT COUNT(*) FROM generation_jobs WHERE status = 'running'").fetchone()[0])


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
            create_image_record(entry, commit=False)
        db.execute(
            "UPDATE generation_jobs SET status = 'completed', completed_at = ? WHERE id = ?",
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


def process_generation_job(job: dict) -> None:
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
        refund_job(db, job, str(exc))
    finally:
        db.close()


def generation_worker_loop() -> None:
    while True:
        db = open_worker_db()
        try:
            job = claim_next_job(db)
        except Exception:
            job = None
        finally:
            db.close()

        if job:
            process_generation_job(job)
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

            effective_api_key = form_values["api_key"] or DEFAULTS["api_key"]
            if not effective_api_key:
                raise ValueError("请先填写 API Key。")
            if form_values["model_choice"] == "__custom__" and not form_values["custom_model"]:
                raise ValueError("选择自定义模型时，请填写模型名称。")

            client = build_client(effective_api_key, form_values["base_url"])
            original_prompt = form_values["prompt"]
            effective_prompt = (
                polish_prompt_text(original_prompt)
                if form_values["polish_prompt"]
                else original_prompt
            )
            form_values["model"] = form_values["model_choice"]
            resolved_model = resolve_model_name(form_values)
            form_values["model"] = resolved_model
            form_values["prompt"] = effective_prompt
            request_payload = build_image_params(form_values)
            form_values["prompt"] = original_prompt
            response = client.images.generate(**request_payload)

            output_format = request_payload.get("output_format", "png")
            new_history = []
            for item in response.data:
                image_bytes, detected_format = decode_image_payload(item, output_format)
                filename = save_image(image_bytes, detected_format)
                history_entry = {
                    "url": url_for("generated_file", filename=filename),
                    "filename": filename,
                    "user_id": current_user_id(),
                    "visibility": "public",
                    "source": "custom",
                    "revised_prompt": getattr(item, "revised_prompt", None),
                    "prompt": original_prompt,
                    "effective_prompt": effective_prompt,
                    "prompt_polished": form_values["polish_prompt"],
                    "model": request_payload["model"],
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                images.append(history_entry)
                new_history.append(history_entry)

            append_history(new_history)
        except binascii.Error:
            error = "返回的图片数据无法解析，请确认接口兼容 OpenAI 图片返回格式。"
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
