from app import *  # noqa: F401,F403


def running_jobs_count(db: sqlite3.Connection) -> int:
    builtin_running = int(db.execute("SELECT COUNT(*) FROM generation_jobs WHERE status = 'running'").fetchone()[0])
    custom_running = int(db.execute("SELECT COUNT(*) FROM custom_generation_jobs WHERE status = 'running'").fetchone()[0])
    return builtin_running + custom_running


def reset_stale_running_jobs(db: sqlite3.Connection) -> None:
    stale_before = datetime.fromtimestamp(time.time() - WORKER_STALE_RUNNING_SECONDS).strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """
        UPDATE generation_jobs
        SET status = 'pending', started_at = NULL, error_message = ''
        WHERE status = 'running' AND COALESCE(started_at, created_at) < ?
        """,
        (stale_before,),
    )
    db.execute(
        """
        UPDATE custom_generation_jobs
        SET status = 'pending', started_at = NULL, error_message = ''
        WHERE status = 'running' AND COALESCE(started_at, created_at) < ?
        """,
        (stale_before,),
    )


def recover_interrupted_running_jobs() -> None:
    db = open_worker_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """
            UPDATE generation_jobs
            SET status = 'pending', started_at = NULL, error_message = ''
            WHERE status = 'running'
            """
        )
        db.execute(
            """
            UPDATE custom_generation_jobs
            SET status = 'pending', started_at = NULL, error_message = ''
            WHERE status = 'running'
            """
        )
        db.commit()
    except Exception:
        db.rollback()
        app.logger.exception("恢复中断的生成任务失败")
    finally:
        db.close()


def claim_next_job(db: sqlite3.Connection) -> dict | None:
    config = get_provider_config(include_secret=True, db=db)
    max_running = max(1, int(config.get("max_concurrent_jobs", 1) or 1))
    db.execute("BEGIN IMMEDIATE")
    try:
        reset_stale_running_jobs(db)
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
        reset_stale_running_jobs(db)
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
            entry["visibility"] = "public"
            entry["source"] = "custom"
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
        visibility = "public" if job.get("publish_to_gallery") else "private"
        image_entries = []
        for item in response.data:
            image_bytes, detected_format = decode_image_payload(item, output_format)
            filename = save_image(image_bytes, detected_format)
            image_entries.append(
                {
                    "filename": filename,
                    "user_id": job["user_id"],
                    "job_id": job["id"],
                    "visibility": visibility,
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
                app.logger.exception("生成队列领取任务失败")
                job = None
                custom_job = None
            finally:
                db.close()

            if job:
                try:
                    process_generation_job(job)
                except Exception:
                    app.logger.exception("处理内置生成任务失败")
                continue
            if custom_job:
                try:
                    process_custom_generation_job(custom_job)
                except Exception:
                    app.logger.exception("处理自定义生成任务失败")
                continue
            time.sleep(WORKER_POLL_SECONDS)


def start_generation_worker() -> None:
    global WORKER_STARTED, WORKER_THREAD
    with WORKER_LOCK:
        if WORKER_STARTED and WORKER_THREAD and WORKER_THREAD.is_alive():
            return
        recover_interrupted_running_jobs()
        thread = threading.Thread(target=generation_worker_loop, name="generation-worker", daemon=True)
        thread.start()
        WORKER_THREAD = thread
        WORKER_STARTED = True
