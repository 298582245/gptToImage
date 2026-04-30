import base64
import binascii
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory, url_for
from openai import OpenAI


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

DEFAULTS = {
    "base_url": os.getenv("OPENAI_BASE_URL", "https://www.papaclaoud.top"),
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

app = Flask(__name__, static_url_path=f"{BASE_PATH}/static" if BASE_PATH else "/static")


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


def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(history, list):
            return history
    except json.JSONDecodeError:
        return []
    return []


def save_history(history: list[dict]) -> None:
    HISTORY_FILE.write_text(
        json.dumps(history[:120], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_history(entries: list[dict]) -> None:
    history = load_history()
    history = entries + history
    save_history(history)


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
    }
    images = []
    history_items = []
    error = None
    request_payload = None
    model_options = build_fallback_model_options()
    model_status = "当前显示的是内置默认模型列表。"

    if request.method == "POST":
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
            effective_api_key = form_values["api_key"] or DEFAULTS["api_key"]
            if not effective_api_key:
                raise ValueError("请先填写 API Key。")
            if not form_values["prompt"]:
                raise ValueError("请输入提示词。")
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
    return send_from_directory(GENERATED_DIR, filename)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
