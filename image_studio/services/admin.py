from app import *  # noqa: F401,F403


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


def load_recent_images(limit: int = 20) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT images.*, users.username, users.is_admin AS user_is_admin, users.is_disabled AS user_is_disabled
        FROM images
        LEFT JOIN users ON users.id = images.user_id
        ORDER BY images.created_at DESC, images.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [image_row_to_dict(row) for row in rows]


def load_admin_images_page(page: int, per_page: int, username_query: str = "") -> tuple[list[dict], dict]:
    db = get_db()
    username_query = username_query.strip()
    where_clause = ""
    params: list[str] = []
    if username_query:
        where_clause = "WHERE users.username LIKE ?"
        params.append(f"%{username_query}%")

    total = int(
        db.execute(
            f"""
            SELECT COUNT(*)
            FROM images
            LEFT JOIN users ON users.id = images.user_id
            {where_clause}
            """,
            params,
        ).fetchone()[0]
    )
    meta = pagination_meta(total, page, per_page)
    rows = db.execute(
        f"""
        SELECT images.*, users.username, users.is_admin AS user_is_admin, users.is_disabled AS user_is_disabled
        FROM images
        LEFT JOIN users ON users.id = images.user_id
        {where_clause}
        ORDER BY images.created_at DESC, images.id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, meta["per_page"], (meta["page"] - 1) * meta["per_page"]),
    ).fetchall()
    return [image_row_to_dict(row) for row in rows], meta


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
