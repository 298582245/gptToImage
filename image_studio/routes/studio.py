from app import *  # noqa: F401,F403


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
        "polish_category": "auto",
        "generation_mode": "custom",
        "publish_to_gallery": False,
        "confirmed_effective_prompt": "",
        "confirmed_prompt_source": "",
    }
    images = []
    history_items = []
    error = None
    polish_preview = None
    request_payload = None
    model_options = build_fallback_model_options()
    model_status = "当前显示的是内置默认模型列表。"

    if request.method == "POST":
        if not validate_csrf_token():
            abort(400)
        polish_action = request.form.get("polish_action", "confirm")

        for key in form_values:
            if key in {"polish_prompt", "publish_to_gallery"}:
                form_values[key] = to_bool(request.form.get(key, ""))
                continue
            if key == "polish_category":
                value = request.form.get(key, "auto").strip() or "auto"
                form_values[key] = value if value in INSPIRER_CATEGORY_BY_VALUE else "auto"
                continue
            if key == "confirmed_effective_prompt":
                form_values[key] = request.form.get(key, "").strip()
                continue
            if key == "confirmed_prompt_source":
                form_values[key] = request.form.get(key, "").strip()
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
            if not form_values["prompt"]:
                raise ValueError("请输入提示词。")

            if form_values["generation_mode"] == "builtin":
                if form_values["polish_prompt"]:
                    confirmed_source = form_values["confirmed_prompt_source"]
                    if polish_action == "repolish" or not form_values["confirmed_effective_prompt"] or confirmed_source != form_values["prompt"]:
                        polish_preview = build_builtin_polish_preview(form_values)
                        form_values["confirmed_effective_prompt"] = polish_preview["effective_prompt"]
                        form_values["confirmed_prompt_source"] = form_values["prompt"]
                    else:
                        job_id = create_builtin_job(form_values)
                        flash("内置接口任务已提交，请在任务列表查看生成进度。")
                        return redirect(url_for("my_jobs", job_id=job_id))
                else:
                    job_id = create_builtin_job(form_values)
                    flash("内置接口任务已提交，请在任务列表查看生成进度。")
                    return redirect(url_for("my_jobs", job_id=job_id))

            else:
                if form_values["polish_prompt"]:
                    confirmed_source = form_values["confirmed_prompt_source"]
                    if polish_action == "repolish" or not form_values["confirmed_effective_prompt"] or confirmed_source != form_values["prompt"]:
                        polish_preview = build_custom_polish_preview(form_values)
                        form_values["confirmed_effective_prompt"] = polish_preview["effective_prompt"]
                        form_values["confirmed_prompt_source"] = form_values["prompt"]
                    else:
                        access_token = create_custom_job(form_values)
                        flash("任务已提交，生成完成后会自动显示结果。")
                        return redirect(url_for("custom_job_status", access_token=access_token))
                else:
                    access_token = create_custom_job(form_values)
                    flash("任务已提交，生成完成后会自动显示结果。")
                    return redirect(url_for("custom_job_status", access_token=access_token))
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
        polish_preview=polish_preview,
        request_payload=request_payload,
        model_options=model_options,
        model_status=model_status,
        provider_config=get_provider_config(),
        inspirer_categories=INSPIRER_CATEGORIES,
        inspirer_source_url=IMAGE_INSPIRER_SOURCE_URL,
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
    row = get_db().execute(
        "SELECT id, filename, user_id, visibility FROM images WHERE filename = ?",
        (filename,),
    ).fetchone()
    if row and row["visibility"] == "hidden":
        user = g.get("current_user")
        if not user or not user.get("is_admin"):
            abort(404)
    elif row and row["visibility"] != "public":
        user = g.get("current_user")
        if not user or (not user.get("is_admin") and user["id"] != row["user_id"]):
            abort(404)
    return send_from_directory(GENERATED_DIR, filename)
