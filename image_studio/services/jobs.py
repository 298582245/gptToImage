from app import *  # noqa: F401,F403


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

    price_per_image = int(config.get("price_per_image", 1))
    original_prompt = form_values["prompt"]
    effective_prompt = form_values.get("confirmed_effective_prompt", "").strip()
    confirmed_source = form_values.get("confirmed_prompt_source", "").strip()
    if effective_prompt and confirmed_source != original_prompt:
        raise ValueError("润色确认已失效，请重新确认提示词。")
    if not effective_prompt:
        effective_prompt = polish_prompt_text(original_prompt, form_values.get("polish_category", "auto")) if form_values["polish_prompt"] else original_prompt
    request_params = build_image_params(
        {
            "model": config.get("model") or DEFAULTS["model"],
            "prompt": effective_prompt,
            "size": form_values["size"],
            "quality": form_values["quality"],
            "background": form_values["background"],
            "output_format": form_values["output_format"],
            "style": form_values.get("style", "vivid"),
            "n": form_values["n"],
        }
    )
    actual_n = int(request_params["n"])
    cost = price_per_image * actual_n

    try:
        db.execute("BEGIN IMMEDIATE")
        if user_active_jobs_count(db, user_id) >= int(config.get("per_user_pending_limit", 3)):
            raise ValueError("你当前排队或生成中的任务太多，请稍后再提交。")
        cursor = db.execute(
            """
            INSERT INTO generation_jobs (
                user_id, status, prompt, effective_prompt, prompt_polished, model,
                size, quality, background, output_format, style, n, cost, publish_to_gallery, created_at
            ) VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                original_prompt,
                effective_prompt,
                1 if form_values["polish_prompt"] else 0,
                request_params["model"],
                request_params.get("size", ""),
                request_params.get("quality", ""),
                request_params.get("background", ""),
                request_params.get("output_format", "png"),
                request_params.get("style", form_values.get("style", "vivid")),
                actual_n,
                cost,
                1 if form_values.get("publish_to_gallery") else 0,
                now_text(),
            ),
        )
        job_id = cursor.lastrowid
        add_credit_ledger(db, user_id, -cost, f"图片生成扣费：{price_per_image} 积分/张 × {actual_n} 张", job_id)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return job_id


def create_custom_job(form_values: dict) -> str:
    effective_api_key = form_values["api_key"].strip()
    if not effective_api_key:
        raise ValueError("请先填写 API Key。")
    if form_values["model_choice"] == "__custom__" and not form_values["custom_model"]:
        raise ValueError("选择自定义模型时，请填写模型名称。")

    original_prompt = form_values["prompt"]
    effective_prompt = form_values.get("confirmed_effective_prompt", "").strip()
    confirmed_source = form_values.get("confirmed_prompt_source", "").strip()
    if effective_prompt and confirmed_source != original_prompt:
        raise ValueError("润色确认已失效，请重新确认提示词。")
    if not effective_prompt:
        effective_prompt = polish_prompt_text(original_prompt, form_values.get("polish_category", "auto")) if form_values["polish_prompt"] else original_prompt
    resolved_model = resolve_model_name(
        {
            "model": form_values["model_choice"],
            "custom_model": form_values.get("custom_model", ""),
        }
    )
    base_url = validate_public_base_url(form_values["base_url"] or DEFAULTS["base_url"])
    request_params = build_image_params(
        {
            "model": resolved_model,
            "prompt": effective_prompt,
            "size": form_values["size"],
            "quality": form_values["quality"],
            "background": form_values["background"],
            "output_format": form_values["output_format"],
            "style": form_values.get("style", "vivid"),
            "n": form_values["n"],
        }
    )
    actual_n = int(request_params["n"])
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
            base_url,
            encrypt_secret(effective_api_key),
            request_params["model"],
            request_params.get("size", ""),
            request_params.get("quality", ""),
            request_params.get("background", ""),
            request_params.get("output_format", "png"),
            request_params.get("style", form_values.get("style", "vivid")),
            actual_n,
            now_text(),
        ),
    )
    db.commit()
    return access_token


def build_builtin_polish_preview(form_values: dict) -> dict:
    user_id = current_user_id()
    if user_id is None:
        raise ValueError("请先登录后再使用内置接口。")
    db = get_db()
    config = get_provider_config(db=db)
    if not config.get("enabled") or not config.get("has_api_key") or not config.get("base_url"):
        raise ValueError("内置接口暂未启用，请联系管理员配置。")
    polish_price = max(0, int(config.get("polish_price", 0) or 0))
    if polish_price > 0:
        user = db.execute("SELECT credits FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user or int(user["credits"]) < polish_price:
            raise ValueError("积分不足，无法使用提示词润色。")

    original_prompt = form_values["prompt"].strip()
    effective_prompt = polish_prompt_with_ai(original_prompt, form_values.get("polish_category", "auto"))
    if polish_price > 0:
        add_credit_ledger(db, user_id, -polish_price, "提示词润色扣费")
        db.commit()
    return {
        "original_prompt": original_prompt,
        "effective_prompt": effective_prompt,
        "category": resolve_inspirer_category(original_prompt, form_values.get("polish_category", "auto")),
        "polish_price": polish_price,
    }


def build_custom_polish_preview(form_values: dict) -> dict:
    original_prompt = form_values["prompt"].strip()
    category = resolve_inspirer_category(original_prompt, form_values.get("polish_category", "auto"))
    return {
        "original_prompt": original_prompt,
        "effective_prompt": polish_prompt_text(original_prompt, form_values.get("polish_category", "auto")),
        "category": category,
    }


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


def load_user_jobs_page(user_id: int, page: int, per_page: int) -> tuple[list[dict], dict]:
    db = get_db()
    total = int(db.execute("SELECT COUNT(*) FROM generation_jobs WHERE user_id = ?", (user_id,)).fetchone()[0])
    meta = pagination_meta(total, page, per_page)
    rows = db.execute(
        """
        SELECT jobs.*, COUNT(images.id) AS image_count
        FROM generation_jobs AS jobs
        LEFT JOIN images ON images.job_id = jobs.id
        WHERE jobs.user_id = ?
        GROUP BY jobs.id
        ORDER BY jobs.created_at DESC, jobs.id DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, meta["per_page"], (meta["page"] - 1) * meta["per_page"]),
    ).fetchall()
    return [job_row_to_dict(row) for row in rows], meta


def load_job_images(job_id: int) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT images.*, users.username
        FROM images
        LEFT JOIN users ON users.id = images.user_id
        WHERE images.job_id = ? AND images.visibility != 'hidden'
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
        WHERE images.access_token = ? AND images.visibility != 'hidden'
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
