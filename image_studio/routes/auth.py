from app import *  # noqa: F401,F403


@app.route(route_path("/login"), methods=["GET", "POST"])
def login():
    if g.get("current_user"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        if not validate_csrf_token():
            abort(400)
        username = normalize_username(request.form.get("username", ""))
        password = request.form.get("password", "")
        user = get_user_with_password(username)
        if user and check_password_hash(user["password_hash"], password):
            if user["is_disabled"]:
                error = "账号已被禁用，请联系管理员。"
                return render_template("auth.html", mode="login", error=error)
            session.clear()
            session["user_id"] = user["id"]
            get_csrf_token()
            return redirect(url_for("index"))
        error = "用户名或密码不正确。"

    return render_template("auth.html", mode="login", error=error)


@app.route(route_path("/register"), methods=["GET", "POST"])
def register():
    if g.get("current_user"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        if not validate_csrf_token():
            abort(400)
        username = normalize_username(request.form.get("username", ""))
        password = request.form.get("password", "")
        error = validate_auth_form(username, password)
        if error is None:
            try:
                user = create_user(username, password)
                session.clear()
                session["user_id"] = user["id"]
                get_csrf_token()
                flash("注册成功，已自动登录。")
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                error = "这个用户名已经被占用。"

    return render_template("auth.html", mode="register", error=error)


@app.post(route_path("/logout"))
def logout():
    if not validate_csrf_token():
        abort(400)
    session.clear()
    return redirect(url_for("index"))
