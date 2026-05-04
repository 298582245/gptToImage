from app import *  # noqa: F401,F403


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
    page, per_page = parse_page_params(12, (6, 12, 24, 48))
    username_query = request.args.get("username", "").strip()
    recent_images, pagination = load_admin_images_page(page, per_page, username_query)
    return render_template(
        "admin_images.html",
        active_admin_page="images",
        recent_images=recent_images,
        pagination=pagination,
        username_query=username_query,
    )


@app.post(route_path("/admin/images/<int:image_id>/hide"))
@admin_required
def admin_image_hide(image_id: int):
    if not validate_csrf_token():
        abort(400)
    try:
        current = g.get("current_user")
        db = get_db()
        image = db.execute(
            """
            SELECT images.id, images.user_id, images.visibility, users.is_admin, users.is_disabled
            FROM images
            LEFT JOIN users ON users.id = images.user_id
            WHERE images.id = ?
            """,
            (image_id,),
        ).fetchone()
        if not image:
            raise ValueError("图片不存在。")

        db.execute("UPDATE images SET visibility = 'hidden' WHERE id = ?", (image_id,))
        ban_user = request.form.get("ban_user") == "on"
        ban_skipped = False
        if ban_user and image["user_id"]:
            if image["is_admin"] or (current and int(current["id"]) == int(image["user_id"])):
                ban_skipped = True
            else:
                db.execute("UPDATE users SET is_disabled = 1 WHERE id = ?", (image["user_id"],))
        db.commit()
        flash("图片已隐藏，仅管理员可查看。" + (" 已跳过封禁管理员账号。" if ban_skipped else ""))
    except Exception as exc:  # noqa: BLE001
        get_db().rollback()
        flash(f"隐藏图片失败：{exc}")
    return redirect(
        url_for(
            "admin_images",
            page=request.args.get("page", 1),
            per_page=request.args.get("per_page", 12),
            username=request.args.get("username", "").strip(),
        )
    )


@app.post(route_path("/admin/images/<int:image_id>/restore"))
@admin_required
def admin_image_restore(image_id: int):
    if not validate_csrf_token():
        abort(400)
    try:
        db = get_db()
        image = db.execute(
            """
            SELECT images.id, images.source, generation_jobs.publish_to_gallery
            FROM images
            LEFT JOIN generation_jobs ON generation_jobs.id = images.job_id
            WHERE images.id = ?
            """,
            (image_id,),
        ).fetchone()
        if not image:
            raise ValueError("图片不存在。")
        restored_visibility = "private"
        if image["source"] != "builtin" or image["publish_to_gallery"]:
            restored_visibility = "public"
        db.execute("UPDATE images SET visibility = ? WHERE id = ?", (restored_visibility, image_id))
        db.commit()
        flash("图片已恢复显示。")
    except Exception as exc:  # noqa: BLE001
        get_db().rollback()
        flash(f"恢复图片失败：{exc}")
    return redirect(
        url_for(
            "admin_images",
            page=request.args.get("page", 1),
            per_page=request.args.get("per_page", 12),
            username=request.args.get("username", "").strip(),
        )
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
