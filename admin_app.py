import os
import re
from pathlib import Path

from flask import Flask, render_template, request, redirect, flash, url_for
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv

from app.db.base import Base
from app.db.session import db_session
from app.tools.import_csv import load_file
from app.tools.zip_helper import extract_zip
from datetime import datetime

from app.db.models import AdminUser

# ─────────────────────────────
load_dotenv()

ZIP_PASSWORD = os.getenv("ZIP_PASSWORD") or ""
ALLOWED_EXT = {".csv", ".txt", ".xls", ".xlsx", ".zip"}

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "some-secret-key")
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─────────────────────────────
# Flask-Login

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    return db_session.get(AdminUser, int(user_id))


# ─────────────────────────────
# Логин / логаут

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = db_session.query(AdminUser).filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("upload_file"))
        flash("❌ Неверный логин или пароль", "error")
        return redirect("/login")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/login")


# ─────────────────────────────
# Загрузка файла

@app.route("/", methods=["GET", "POST"])
@login_required
def upload_file():
    if request.method == "POST":
        f = request.files.get("file")
        src = request.form.get("src", "main")
        ext = Path(f.filename).suffix.lower()

        if not f or ext not in ALLOWED_EXT:
            flash("⚠️ Разрешены CSV / TXT / XLS / XLSX / ZIP", "error")
            return redirect("/")

        filepath = Path(UPLOAD_FOLDER) / f.filename
        f.save(filepath)

        # ───────── ZIP? ─────────
        if filepath.suffix.lower() == ".zip":
            if not ZIP_PASSWORD:
                flash("❌ В .env нет ZIP_PASSWORD", "error")
                return redirect("/")
            try:
                filepath, file_dt = extract_zip(filepath, ZIP_PASSWORD)
            except Exception as e:
                flash(f"❌ Не удалось распаковать ZIP: {e}", "error")
                return redirect("/")
        else:
            # берём mtime если дату не нашли в имени
            m = re.search(r"(\d{4})[-_](\d{2})[-_](\d{2})[_-](\d{2})[-_](\d{2})", filepath.stem)
            if m:
                y, M, d, H, m_ = map(int, m.groups())
                file_dt = datetime(y, M, d, H, m_)
            else:
                file_dt = datetime.fromtimestamp(filepath.stat().st_mtime)

        try:
            # rows = load_file(filepath, replace=True, file_dt=file_dt)
            rows = load_file(filepath,
                             src=src,
                             file_dt=file_dt)
            flash(f"✅ Импортировано строк: {rows}", "success")
        except Exception as e:
            flash(f"❌ Ошибка: {e}", "error")

        return redirect("/")

    pwa_users = db_session.query(AdminUser).order_by(AdminUser.username).all()
    return render_template("upload.html", pwa_users=pwa_users)


# ─────────────────────────────
def create_admin_user():
    username = os.getenv("ADMIN_USERNAME") or "admin"
    password = os.getenv("ADMIN_PASSWORD") or "adminpass"

    Base.metadata.create_all(bind=db_session.bind)

    if not db_session.query(AdminUser).filter_by(username=username).first():
        user = AdminUser(username=username)
        user.set_password(password)
        db_session.add(user)
        db_session.commit()


@app.post("/user/add")
@login_required
def user_add():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        flash("Логин и пароль обязательны.", "error")
        return redirect(url_for("upload_file"))

    if not re.fullmatch(r'[a-zA-Z0-9_\-]+', username):
        flash("Логин: только латинские буквы, цифры, _ и -", "error")
        return redirect(url_for("upload_file"))

    if db_session.query(AdminUser).filter_by(username=username).first():
        flash(f"Пользователь «{username}» уже существует.", "warning")
        return redirect(url_for("upload_file"))

    u = AdminUser(username=username)
    u.set_password(password)
    db_session.add(u)
    db_session.commit()
    flash(f"✅ Пользователь «{username}» добавлен.", "success")
    return redirect(url_for("upload_file"))


@app.post("/user/del/<int:user_id>")
@login_required
def user_del(user_id: int):
    if current_user.id == user_id:
        flash("Нельзя удалить самого себя.", "error")
        return redirect(url_for("upload_file"))

    u = db_session.get(AdminUser, user_id)
    if u:
        db_session.delete(u)
        db_session.commit()
        flash(f"🗑 Пользователь «{u.username}» удалён.", "success")
    else:
        flash("Пользователь не найден.", "error")
    return redirect(url_for("upload_file"))


if __name__ == "__main__":
    with app.app_context():
        create_admin_user()

    app.run(host="0.0.0.0", port=5102)
