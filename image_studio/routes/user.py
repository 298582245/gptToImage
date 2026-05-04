from app import *  # noqa: F401,F403


@app.route(route_path("/my/images"))
@login_required
def my_images():
    page, per_page = parse_page_params(12, (6, 12, 24, 48))
    images, pagination = load_user_images_page(current_user_id(), page, per_page)
    return render_template("my_images.html", images=images, pagination=pagination)


@app.post(route_path("/my/images/<int:image_id>/visibility"))
@login_required
def update_my_image_visibility(image_id: int):
    if not validate_csrf_token():
        abort(400)
    visibility = request.form.get("visibility", "").strip()
    if visibility not in {"public", "private"}:
        abort(400)

    db = get_db()
    image = db.execute(
        "SELECT id, user_id, visibility FROM images WHERE id = ?",
        (image_id,),
    ).fetchone()
    if not image or int(image["user_id"] or 0) != int(current_user_id()):
        abort(404)
    if image["visibility"] == "hidden":
        flash("这张图片已被管理员隐藏，不能自行修改可见性。")
        return redirect(url_for("my_images"))

    db.execute("UPDATE images SET visibility = ? WHERE id = ?", (visibility, image_id))
    db.commit()
    flash("图片可见性已更新。")
    return redirect(url_for("my_images", page=request.args.get("page", 1), per_page=request.args.get("per_page", 12)))


@app.route(route_path("/my/jobs"))
@login_required
def my_jobs():
    selected_job_id = request.args.get("job_id", type=int)
    page, per_page = parse_page_params(5, (5, 10, 20, 50))
    jobs, pagination = load_user_jobs_page(current_user_id(), page, per_page)
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
    return render_template(
        "my_jobs.html",
        jobs=jobs,
        selected_job=selected_job,
        selected_images=selected_images,
        pagination=pagination,
    )


@app.route(route_path("/my/credits"))
@login_required
def my_credits():
    page, per_page = parse_page_params(10, (10, 20, 50, 100))
    records, pagination = load_user_credit_records_page(current_user_id(), page, per_page)
    return render_template("my_credits.html", records=records, pagination=pagination)


@app.get(route_path("/api/my/jobs"))
@login_required
def api_my_jobs():
    jobs = load_user_jobs(current_user_id(), limit=50)
    return jsonify({"ok": True, "jobs": jobs})


@app.route(route_path("/jobs/<access_token>"))
def custom_job_status(access_token: str):
    job = load_custom_job(access_token)
    if not job:
        abort(404)
    images = load_custom_job_images(access_token)
    return render_template("custom_job.html", job=job, images=images)


@app.get(route_path("/api/jobs/<access_token>"))
def api_custom_job(access_token: str):
    job = load_custom_job(access_token)
    if not job:
        abort(404)
    images = load_custom_job_images(access_token)
    return jsonify({"ok": True, "job": job, "image_count": len(images)})


@app.route(route_path("/recharge"), methods=["GET", "POST"])
@login_required
def recharge():
    if request.method == "POST":
        if not validate_csrf_token():
            abort(400)
        try:
            result = redeem_code_for_user(request.form.get("code", ""), current_user_id())
            flash(f"充值成功，到账 {result['credits']} 积分，当前余额 {result['balance']}。")
            return redirect(url_for("recharge"))
        except Exception as exc:  # noqa: BLE001
            flash(f"充值失败：{exc}")

    return render_template(
        "recharge.html",
        settings=get_recharge_settings(),
        recent_uses=load_user_redeem_uses(current_user_id(), limit=10),
    )
