from app import *  # noqa: F401,F403


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
