from app import *  # noqa: F401,F403


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
    visibility = row["visibility"]
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
        "visibility": visibility,
        "visibility_label": {"public": "公开", "private": "私有", "hidden": "已隐藏"}.get(visibility, visibility),
        "source": row["source"],
        "user_id": row["user_id"],
        "username": row["username"] if "username" in row.keys() else None,
        "user_is_admin": bool(row["user_is_admin"]) if "user_is_admin" in row.keys() and row["user_is_admin"] is not None else False,
        "user_is_disabled": bool(row["user_is_disabled"]) if "user_is_disabled" in row.keys() and row["user_is_disabled"] is not None else False,
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
        WHERE images.user_id = ? AND images.visibility != 'hidden'
        ORDER BY images.created_at DESC, images.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [image_row_to_dict(row) for row in rows]


def load_user_images_page(user_id: int, page: int, per_page: int) -> tuple[list[dict], dict]:
    db = get_db()
    total = int(
        db.execute(
            "SELECT COUNT(*) FROM images WHERE user_id = ? AND visibility != 'hidden'",
            (user_id,),
        ).fetchone()[0]
    )
    meta = pagination_meta(total, page, per_page)
    rows = db.execute(
        """
        SELECT images.*, users.username
        FROM images
        LEFT JOIN users ON users.id = images.user_id
        WHERE images.user_id = ? AND images.visibility != 'hidden'
        ORDER BY images.created_at DESC, images.id DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, meta["per_page"], (meta["page"] - 1) * meta["per_page"]),
    ).fetchall()
    return [image_row_to_dict(row) for row in rows], meta
