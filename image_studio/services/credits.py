from app import *  # noqa: F401,F403


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


def credit_record_type(reason: str) -> str:
    if "润色" in reason:
        return "提示词润色"
    if "退款" in reason or "取消" in reason:
        return "积分退款"
    if "生成" in reason or "画图" in reason:
        return "图片生成"
    if "充值" in reason or "卡密" in reason:
        return "积分充值"
    if "管理员" in reason:
        return "管理员调整"
    return "其他"


def load_user_credit_records(user_id: int, limit: int = 100) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT ledger.*, jobs.n AS image_count, jobs.model AS job_model
        FROM credit_ledger AS ledger
        LEFT JOIN generation_jobs AS jobs ON jobs.id = ledger.job_id
        WHERE ledger.user_id = ?
        ORDER BY ledger.created_at DESC, ledger.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    records = []
    for row in rows:
        record = dict(row)
        record["type_label"] = credit_record_type(record["reason"])
        record["amount_label"] = f"+{record['amount']}" if int(record["amount"]) > 0 else str(record["amount"])
        records.append(record)
    return records


def load_user_credit_records_page(user_id: int, page: int, per_page: int) -> tuple[list[dict], dict]:
    db = get_db()
    total = int(db.execute("SELECT COUNT(*) FROM credit_ledger WHERE user_id = ?", (user_id,)).fetchone()[0])
    meta = pagination_meta(total, page, per_page)
    rows = db.execute(
        """
        SELECT ledger.*, jobs.n AS image_count, jobs.model AS job_model
        FROM credit_ledger AS ledger
        LEFT JOIN generation_jobs AS jobs ON jobs.id = ledger.job_id
        WHERE ledger.user_id = ?
        ORDER BY ledger.created_at DESC, ledger.id DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, meta["per_page"], (meta["page"] - 1) * meta["per_page"]),
    ).fetchall()
    records = []
    for row in rows:
        record = dict(row)
        record["type_label"] = credit_record_type(record["reason"])
        record["amount_label"] = f"+{record['amount']}" if int(record["amount"]) > 0 else str(record["amount"])
        records.append(record)
    return records, meta
