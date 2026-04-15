import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, render_template, request, redirect, flash, url_for
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv
from sqlalchemy import func

from app.db.base import Base
from app.db.session import db_session
from app.tools.import_csv import load_file
from app.tools.zip_helper import extract_zip

from app.db.models import AdminUser, PwaActivity, InnDiler, InnLpu, InnPending
from app.tools.import_supplies import load_supplies_file

# ─────────────────────────────
load_dotenv()

ZIP_PASSWORD = os.getenv("ZIP_PASSWORD") or ""
ALLOWED_EXT = {".csv", ".txt", ".xls", ".xlsx", ".zip"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "some-secret-key")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024  # лимит загрузки
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _cleanup_stale_uploads(max_age_hours: int = 2) -> None:
    """Удаляет файлы из uploads/, оставшиеся от прерванных импортов."""
    cutoff = datetime.now().timestamp() - max_age_hours * 3600
    for f in Path(UPLOAD_FOLDER).iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


# Чистим зависшие загрузки при старте
_cleanup_stale_uploads()

# ─────────────────────────────
# Flask-Login

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@app.errorhandler(413)
def too_large(_):
    flash(f"❌ Файл слишком большой. Максимум {MAX_UPLOAD_MB} МБ.", "error")
    return redirect(request.referrer or url_for("upload_file"))


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

@app.route("/", methods=["GET"])
@login_required
def upload_file():
    pwa_users = db_session.query(AdminUser).order_by(AdminUser.username).all()
    return render_template("upload.html", pwa_users=pwa_users)


# ─────────────────────────────
# Загрузка файла имплантов

@app.route("/implants/upload", methods=["GET", "POST"])
@login_required
def implants_upload():
    if request.method == "POST":
        f = request.files.get("file")
        src = request.form.get("src", "main")
        ext = Path(f.filename).suffix.lower()

        if not f or ext not in ALLOWED_EXT:
            flash("⚠️ Разрешены CSV / TXT / XLS / XLSX / ZIP", "error")
            return redirect(url_for("implants_upload"))

        filepath = Path(UPLOAD_FOLDER) / f.filename
        f.save(filepath)

        # ───────── ZIP? ─────────
        if filepath.suffix.lower() == ".zip":
            if not ZIP_PASSWORD:
                flash("❌ В .env нет ZIP_PASSWORD", "error")
                return redirect(url_for("implants_upload"))
            try:
                filepath, file_dt = extract_zip(filepath, ZIP_PASSWORD)
            except Exception as e:
                flash(f"❌ Не удалось распаковать ZIP: {e}", "error")
                return redirect(url_for("implants_upload"))
        else:
            m = re.search(r"(\d{4})[-_](\d{2})[-_](\d{2})[_-](\d{2})[-_](\d{2})", filepath.stem)
            if m:
                y, M, d, H, m_ = map(int, m.groups())
                file_dt = datetime(y, M, d, H, m_)
            else:
                file_dt = datetime.fromtimestamp(filepath.stat().st_mtime)

        try:
            rows = load_file(filepath, src=src, file_dt=file_dt)
            flash(f"✅ Импортировано строк: {rows}", "success")
        except Exception as e:
            flash(f"❌ Ошибка: {e}", "error")
        finally:
            filepath.unlink(missing_ok=True)

        return redirect(url_for("implants_upload"))

    return render_template("implants_upload.html")


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


ALL_MODULES = ["implants", "implants_view", "supplies", "inn_check"]

# ─────────────────────────────
# Загрузка файла расходников

@app.route("/supplies/upload", methods=["GET", "POST"])
@login_required
def supplies_upload():
    if request.method == "POST":
        f = request.files.get("file")
        if not f or Path(f.filename).suffix.lower() not in {".csv", ".txt", ".xls", ".xlsx"}:
            flash("⚠️ Разрешены CSV / TXT / XLS / XLSX", "error")
            return redirect(url_for("supplies_upload"))

        filepath = Path(UPLOAD_FOLDER) / f.filename
        f.save(filepath)
        try:
            rows = load_supplies_file(filepath)
            flash(f"✅ Расходники: импортировано строк: {rows}", "success")
        except Exception as e:
            flash(f"❌ Ошибка: {e}", "error")
        finally:
            filepath.unlink(missing_ok=True)
        return redirect(url_for("supplies_upload"))

    return render_template("supplies_upload.html")


# ─────────────────────────────
# Загрузка CSV для проверки ИНН

@app.route("/inn/upload", methods=["GET", "POST"])
@login_required
def inn_upload():
    if request.method == "POST":
        f = request.files.get("file")
        table = request.form.get("table", "")
        if not f or Path(f.filename).suffix.lower() != ".csv":
            flash("⚠️ Разрешены только CSV-файлы", "error")
            return redirect(url_for("inn_upload"))
        if table not in ("dilers", "lpu", "pending"):
            flash("⚠️ Неверная таблица", "error")
            return redirect(url_for("inn_upload"))

        filepath = Path(UPLOAD_FOLDER) / f.filename
        f.save(filepath)
        try:
            import pandas as pd
            df = pd.read_csv(filepath, encoding="cp1251", dtype={"inn": str},
                             sep=",", skipinitialspace=True)
            df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
            df["inn"] = df["inn"].astype(str)
            df["name"] = df["name"].astype(str)

            if table == "dilers":
                db_session.query(InnDiler).delete()
                for _, row in df.iterrows():
                    db_session.add(InnDiler(name=row["name"], inn=row["inn"], allowed=1))
            elif table == "lpu":
                db_session.query(InnLpu).delete()
                for _, row in df.iterrows():
                    db_session.add(InnLpu(name=row["name"], inn=row["inn"], allowed=1))
            elif table == "pending":
                db_session.query(InnPending).delete()
                for _, row in df.iterrows():
                    db_session.add(InnPending(
                        name=row["name"], inn=row["inn"],
                        date=str(row.get("date", "") or ""),
                        approved=int(bool(row.get("approved", False))),
                        denied=int(bool(row.get("denied", False))),
                    ))
            db_session.commit()
            flash(f"✅ ИНН ({table}): загружено {len(df)} записей", "success")
        except Exception as e:
            db_session.rollback()
            flash(f"❌ Ошибка: {e}", "error")
        finally:
            filepath.unlink(missing_ok=True)
        return redirect(url_for("inn_upload"))

    counts = {
        "dilers":  db_session.query(InnDiler).count(),
        "lpu":     db_session.query(InnLpu).count(),
        "pending": db_session.query(InnPending).count(),
    }
    return render_template("inn_upload.html", counts=counts)


@app.post("/user/modules/<int:user_id>")
@login_required
def user_set_modules(user_id: int):
    u = db_session.get(AdminUser, user_id)
    if not u:
        flash("Пользователь не найден.", "error")
        return redirect(url_for("upload_file"))

    selected = [m for m in ALL_MODULES if request.form.get(f"mod_{m}")]
    u.modules = json.dumps(selected)
    db_session.commit()
    flash(f"✅ Модули пользователя «{u.username}» обновлены: {', '.join(selected) or 'нет доступа'}.", "success")
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


ACTION_LABELS = {
    "login":       "Вход",
    "search":      "Поиск",
    "pdf_export":  "Экспорт PDF",
    "add_to_cart": "В корзину",
    "place_order": "Заказ",
    "inn_check":   "Проверка ИНН",
}

ACTION_COLORS = {
    "login":       "primary",
    "search":      "success",
    "pdf_export":  "warning",
    "add_to_cart": "info",
    "place_order": "danger",
    "inn_check":   "secondary",
}


MODULE_LABELS = {
    "implants":      "Импланты",
    "implants_view": "Импланты (просмотр)",
    "supplies":      "Расходники",
}

INN_STATUS_LABELS = {
    "approved":    "✅ Разрешено",
    "denied":      "❌ Запрещено",
    "denied_date": "❌ Запрещено",
    "pending":     "⏳ На рассмотрении",
    "not_found":   "❓ Не найден",
}


def _format_detail(action: str, detail: dict) -> str:
    if not detail:
        return "—"
    if action == "search":
        parts = []
        mod = detail.get("module")
        if mod:
            parts.append(f"[{MODULE_LABELS.get(mod, mod)}]")
        if detail.get("search"):
            parts.append(f"«{detail['search']}»")
        filters = [v for k, v in detail.items()
                   if k not in ("search", "results", "module") and v and v != "все"]
        if filters:
            parts.append(f"фильтры: {', '.join(str(f) for f in filters)}")
        if "results" in detail:
            parts.append(f"найдено: {detail['results']}")
        return " | ".join(parts) if parts else "—"
    if action == "pdf_export":
        parts = []
        mod = detail.get("module")
        if mod:
            parts.append(f"[{MODULE_LABELS.get(mod, mod)}]")
        filters = [v for k, v in detail.items() if k != "module" and v and v != "все"]
        if filters:
            parts.append(", ".join(str(f) for f in filters))
        return " | ".join(parts) if parts else "всё"
    if action == "add_to_cart":
        nom = detail.get("nomenclature", "")
        char = detail.get("characteristic", "")
        qty = detail.get("quantity", "")
        return f"{nom[:50]} {char[:20]} × {qty}".strip()
    if action == "place_order":
        return f"Заказ #{detail.get('order_id')} | ЛПУ: {detail.get('lpu')} | {detail.get('items_count')} поз."
    if action == "inn_check":
        org = "Дилер" if detail.get("org_type") == "diler" else "ЛПУ"
        status = INN_STATUS_LABELS.get(detail.get("status", ""), detail.get("status", ""))
        name = detail.get("name") or ""
        inn = detail.get("inn", "")
        return f"{org} {inn}" + (f" — {name}" if name else "") + f" → {status}"
    return "—"


MODULE_DISPLAY = {
    "implants":      ("⚕️ Импланты (заказ)",     "primary"),
    "implants_view": ("⚕️ Импланты (просмотр)",  "info"),
    "supplies":      ("🔧 Расходники",            "success"),
    "inn_check":     ("🔍 Проверка ИНН",          "secondary"),
    "login":         ("🔑 Входы",                 "dark"),
}


def _activity_module(action: str, detail: dict) -> str:
    """Определяет модуль по действию и detail."""
    if action == "login":
        return "login"
    if action in ("add_to_cart", "place_order"):
        return "implants"
    if action == "inn_check":
        return "inn_check"
    # search / pdf_export — модуль хранится в detail
    return detail.get("module") or "implants"


@app.route("/stats")
@login_required
def stats():
    date_from_str = request.args.get("date_from", "")
    date_to_str   = request.args.get("date_to", "")
    user_id       = request.args.get("user_id", type=int)
    action_filter = request.args.get("action", "")
    module_filter = request.args.get("module", "")

    today = datetime.utcnow().date()
    period_set = bool(date_from_str or date_to_str)

    # ── Запрос для сводной таблицы: за сегодня или за указанный период ──
    pivot_q = db_session.query(PwaActivity)
    if period_set:
        if date_from_str:
            pivot_q = pivot_q.filter(
                PwaActivity.created_at >= datetime.strptime(date_from_str, "%Y-%m-%d"))
        if date_to_str:
            pivot_q = pivot_q.filter(
                PwaActivity.created_at < datetime.strptime(date_to_str, "%Y-%m-%d") + timedelta(days=1))
        if user_id:
            pivot_q = pivot_q.filter(PwaActivity.user_id == user_id)
    else:
        pivot_q = pivot_q.filter(PwaActivity.created_at >= today)

    pivot: dict[str, dict[str, int]] = {}
    for a in pivot_q.all():
        detail = json.loads(a.detail) if a.detail else {}
        mod = _activity_module(a.action, detail)
        pivot.setdefault(mod, {})
        pivot[mod][a.action] = pivot[mod].get(a.action, 0) + 1

    # ── Запрос для журнала: с полными фильтрами ──────────────────────────
    q = db_session.query(PwaActivity).order_by(PwaActivity.created_at.desc())
    if date_from_str:
        q = q.filter(PwaActivity.created_at >= datetime.strptime(date_from_str, "%Y-%m-%d"))
    if date_to_str:
        q = q.filter(PwaActivity.created_at < datetime.strptime(date_to_str, "%Y-%m-%d") + timedelta(days=1))
    if user_id:
        q = q.filter(PwaActivity.user_id == user_id)
    if action_filter:
        q = q.filter(PwaActivity.action == action_filter)

    activities = []
    for a in q.all():
        detail = json.loads(a.detail) if a.detail else {}
        mod = _activity_module(a.action, detail)
        if module_filter and mod != module_filter:
            continue
        if len(activities) >= 1000:
            break
        mod_label, mod_color = MODULE_DISPLAY.get(mod, (mod, "secondary"))
        activities.append({
            "id":         a.id,
            "username":   a.username or "—",
            "action":     a.action,
            "label":      ACTION_LABELS.get(a.action, a.action),
            "color":      ACTION_COLORS.get(a.action, "secondary"),
            "module":     mod,
            "mod_label":  mod_label,
            "mod_color":  mod_color,
            "detail":     _format_detail(a.action, detail),
            "created_at": a.created_at,
        })

    users = db_session.query(AdminUser).order_by(AdminUser.username).all()

    pivot_actions = ["search", "pdf_export", "add_to_cart", "place_order"]

    return render_template(
        "stats.html",
        activities=activities,
        users=users,
        pivot=pivot,
        pivot_actions=pivot_actions,
        period_set=period_set,
        module_display=MODULE_DISPLAY,
        action_labels=ACTION_LABELS,
        filters={
            "date_from": date_from_str,
            "date_to":   date_to_str,
            "user_id":   user_id,
            "action":    action_filter,
            "module":    module_filter,
        },
    )


if __name__ == "__main__":
    with app.app_context():
        create_admin_user()

    app.run(host="0.0.0.0", port=5102)
