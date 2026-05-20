import ipaddress
import socket
from urllib.parse import urlparse

from app import *  # noqa: F401,F403


def validate_public_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if not value:
        return value

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Base URL 必须是有效的 http/https 地址。")
    if parsed.username or parsed.password:
        raise ValueError("Base URL 不允许包含用户名或密码。")

    hostname = parsed.hostname.strip().lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("Base URL 不允许指向本机地址。")

    try:
        addresses = [str(ipaddress.ip_address(hostname))]
    except ValueError:
        try:
            addresses = list({item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)})
        except socket.gaierror as exc:
            raise ValueError("Base URL 域名无法解析。") from exc

    if not addresses:
        raise ValueError("Base URL 域名无法解析。")
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("Base URL 不允许指向内网、本机或保留地址。")
    return value


def normalize_base_url(base_url: str, validate_public: bool = True) -> str:
    value = validate_public_base_url(base_url) if validate_public else base_url.strip().rstrip("/")
    if not value:
        return value
    if value.endswith("/v1"):
        return value
    return f"{value}/v1"


def build_client(api_key: str, base_url: str, max_retries: int | None = None, validate_public_base: bool = True) -> OpenAI:
    kwargs = {"api_key": api_key.strip(), "timeout": OPENAI_CLIENT_TIMEOUT_SECONDS}
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    if base_url.strip():
        kwargs["base_url"] = normalize_base_url(base_url, validate_public=validate_public_base)
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


def get_provider_config(include_secret: bool = False, db: sqlite3.Connection | None = None) -> dict:
    connection = db or get_db()
    row = connection.execute("SELECT * FROM provider_configs WHERE id = 1").fetchone()
    config = dict(row) if row else {}
    api_key_encrypted = config.pop("api_key_encrypted", "")
    polish_api_key_encrypted = config.pop("polish_api_key_encrypted", "")
    config["has_api_key"] = bool(api_key_encrypted)
    config["api_key_masked"] = "已设置" if api_key_encrypted else "未设置"
    config["has_polish_api_key"] = bool(polish_api_key_encrypted)
    config["polish_api_key_masked"] = "已设置" if polish_api_key_encrypted else "未设置"
    if include_secret:
        config["api_key"] = decrypt_secret(api_key_encrypted)
        config["polish_api_key"] = decrypt_secret(polish_api_key_encrypted)
    return config


def update_provider_config(form_data) -> None:
    keep_existing_key = form_data.get("keep_existing_key") == "on"
    keep_existing_polish_key = form_data.get("keep_existing_polish_key") == "on"
    api_key = form_data.get("api_key", "").strip()
    polish_api_key = form_data.get("polish_api_key", "").strip()
    current = get_provider_config(db=get_db())
    encrypted_key = None
    if api_key:
        encrypted_key = encrypt_secret(api_key)
    elif keep_existing_key and current.get("has_api_key"):
        row = get_db().execute("SELECT api_key_encrypted FROM provider_configs WHERE id = 1").fetchone()
        encrypted_key = row["api_key_encrypted"]
    else:
        encrypted_key = ""

    encrypted_polish_key = None
    if polish_api_key:
        encrypted_polish_key = encrypt_secret(polish_api_key)
    elif keep_existing_polish_key and current.get("has_polish_api_key"):
        row = get_db().execute("SELECT polish_api_key_encrypted FROM provider_configs WHERE id = 1").fetchone()
        encrypted_polish_key = row["polish_api_key_encrypted"]
    else:
        encrypted_polish_key = ""

    max_concurrent_jobs = max(1, min(int(form_data.get("max_concurrent_jobs", 1) or 1), 5))
    per_user_pending_limit = max(1, min(int(form_data.get("per_user_pending_limit", 3) or 3), 20))
    price_per_image = max(0, int(form_data.get("price_per_image", 1) or 0))
    polish_price = max(0, int(form_data.get("polish_price", 0) or 0))

    get_db().execute(
        """
        UPDATE provider_configs
        SET base_url = ?, api_key_encrypted = ?, model = ?, price_per_image = ?,
            polish_base_url = ?, polish_api_key_encrypted = ?, polish_model = ?, polish_enabled = ?, polish_price = ?,
            enabled = ?, max_concurrent_jobs = ?, per_user_pending_limit = ?, updated_at = ?
        WHERE id = 1
        """,
        (
            form_data.get("base_url", "").strip(),
            encrypted_key,
            form_data.get("model", "gpt-image-1").strip() or "gpt-image-1",
            price_per_image,
            form_data.get("polish_base_url", "").strip(),
            encrypted_polish_key,
            form_data.get("polish_model", "").strip(),
            1 if form_data.get("polish_enabled") == "on" else 0,
            polish_price,
            1 if form_data.get("enabled") == "on" else 0,
            max_concurrent_jobs,
            per_user_pending_limit,
            now_text(),
        ),
    )
    get_db().commit()
