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

from functools import wraps
from flask import abort

from app.db.models import User, PwaActivity, InnDiler, InnLpu, InnPending
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
    return db_session.get(User, int(user_id))


@app.before_request
def gate_admin_by_superuser():
    """Глобальный гейтинг: все роуты Flask-админки кроме /login, /logout
    и статики требуют is_superuser=1 AND active=1.
    Если пользователь не залогинен — пропускаем дальше, @login_required
    в самом роуте даст редирект на /login."""
    open_endpoints = {"login", "logout", "static"}
    if request.endpoint in open_endpoints or request.endpoint is None:
        return
    if not current_user.is_authenticated:
        return
    if not (current_user.is_superuser and current_user.active):
        abort(403)


@app.errorhandler(403)
def forbidden(_):
    return ("403 Доступ запрещён. "
            "Эта страница доступна только суперпользователям.", 403)


# ─────────────────────────────
# Логин / логаут

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = db_session.query(User).filter_by(username=username).first()
        if user and user.active and user.check_password(password):
            if not user.is_superuser:
                flash("❌ Доступ к админ-панели только у суперпользователей. "
                      "Обычным пользователям — основной сайт PWA.", "error")
                return redirect("/login")
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
    users = db_session.query(User).order_by(
        User.username.is_(None), User.username, User.full_name
    ).all()
    return render_template("upload.html", users=users)


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

    if not db_session.query(User).filter_by(username=username).first():
        user = User(username=username, is_superuser=1, active=1,
                    modules=json.dumps(["implants", "implants_view",
                                        "supplies", "inn_check"]))
        user.set_password(password)
        db_session.add(user)
        db_session.commit()


ALL_MODULES = ["implants", "implants_view", "supplies", "inn_check",
               "bot_supplies", "bot_implants"]


def _parse_modules(form) -> str:
    """Собирает JSON-список модулей из чек-боксов формы."""
    selected = [m for m in ALL_MODULES if form.get(f"mod_{m}")]
    return json.dumps(selected)


def _normalize_tg_id(raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if not raw.lstrip("-").isdigit():
        return "INVALID"
    return int(raw)


@app.post("/user/add")
@login_required
def user_add():
    username = (request.form.get("username") or "").strip() or None
    password = (request.form.get("password") or "").strip() or None
    tg_id_raw = request.form.get("tg_id") or ""
    full_name = (request.form.get("full_name") or "").strip() or None
    title     = (request.form.get("title") or "").strip() or None
    is_super  = 1 if request.form.get("is_superuser") else 0
    active    = 1 if request.form.get("active", "1") else 0

    tg_id = _normalize_tg_id(tg_id_raw)
    if tg_id == "INVALID":
        flash("tg_id должен быть числом.", "error")
        return redirect(url_for("upload_file"))

    if not username and not tg_id:
        flash("Нужно указать хотя бы логин (для PWA) или tg_id (для бота).", "error")
        return redirect(url_for("upload_file"))

    if username:
        if not re.fullmatch(r'[a-zA-Z0-9_\-]+', username):
            flash("Логин: только латинские буквы, цифры, _ и -", "error")
            return redirect(url_for("upload_file"))
        if not password:
            flash("Если указан логин — обязателен пароль.", "error")
            return redirect(url_for("upload_file"))
        if db_session.query(User).filter_by(username=username).first():
            flash(f"Пользователь «{username}» уже существует.", "warning")
            return redirect(url_for("upload_file"))

    if tg_id is not None:
        if db_session.query(User).filter_by(tg_id=tg_id).first():
            flash(f"Пользователь с tg_id {tg_id} уже существует.", "warning")
            return redirect(url_for("upload_file"))

    u = User(username=username, tg_id=tg_id, full_name=full_name, title=title,
             modules=_parse_modules(request.form),
             is_superuser=is_super, active=active)
    if password:
        u.set_password(password)
    db_session.add(u)
    db_session.commit()
    label = username or f"tg:{tg_id}"
    flash(f"✅ Пользователь «{label}» добавлен.", "success")
    return redirect(url_for("upload_file"))

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

INN_MODELS = {
    "dilers":  InnDiler,
    "lpu":     InnLpu,
    "pending": InnPending,
}


@app.route("/inn/upload", methods=["GET", "POST"])
@login_required
def inn_upload():
    if request.method == "POST":
        f = request.files.get("file")
        table = request.form.get("table", "")
        if not f or Path(f.filename).suffix.lower() != ".csv":
            flash("⚠️ Разрешены только CSV-файлы", "error")
            return redirect(url_for("inn_upload"))
        if table not in INN_MODELS:
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

    dilers  = db_session.query(InnDiler).order_by(InnDiler.name).all()
    lpus    = db_session.query(InnLpu).order_by(InnLpu.name).all()
    pending = db_session.query(InnPending).order_by(InnPending.date.desc().nullslast(),
                                                    InnPending.name).all()
    counts = {"dilers": len(dilers), "lpu": len(lpus), "pending": len(pending)}
    return render_template("inn_upload.html",
                           counts=counts,
                           dilers=dilers, lpus=lpus, pending=pending)


@app.post("/inn/add")
@login_required
def inn_add():
    table = request.form.get("table", "")
    name  = (request.form.get("name") or "").strip()
    inn   = (request.form.get("inn") or "").strip()

    if table not in INN_MODELS:
        flash("⚠️ Неверная таблица", "error")
        return redirect(url_for("inn_upload"))
    if not name or not inn:
        flash("⚠️ Заполните название и ИНН", "error")
        return redirect(url_for("inn_upload"))

    Model = INN_MODELS[table]
    if db_session.query(Model).filter_by(inn=inn).first():
        flash(f"⚠️ ИНН {inn} уже есть в таблице", "warning")
        return redirect(url_for("inn_upload"))

    if table == "pending":
        date_str = (request.form.get("date") or "").strip()
        approved = 1 if request.form.get("approved") else 0
        denied   = 1 if request.form.get("denied") else 0
        if denied and not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        rec = InnPending(name=name, inn=inn, date=date_str or None,
                         approved=approved, denied=denied)
    else:
        rec = Model(name=name, inn=inn, allowed=1)

    db_session.add(rec)
    db_session.commit()
    flash(f"✅ Запись «{name}» добавлена", "success")
    return redirect(url_for("inn_upload"))


@app.post("/inn/edit/<string:table>/<int:item_id>")
@login_required
def inn_edit(table, item_id):
    if table not in INN_MODELS:
        flash("⚠️ Неверная таблица", "error")
        return redirect(url_for("inn_upload"))
    Model = INN_MODELS[table]
    rec = db_session.get(Model, item_id)
    if not rec:
        flash("⚠️ Запись не найдена", "error")
        return redirect(url_for("inn_upload"))

    name = (request.form.get("name") or "").strip()
    inn  = (request.form.get("inn") or "").strip()
    if not name or not inn:
        flash("⚠️ Заполните название и ИНН", "error")
        return redirect(url_for("inn_upload"))

    rec.name = name
    rec.inn  = inn
    if table == "pending":
        rec.date     = (request.form.get("date") or "").strip() or None
        rec.approved = 1 if request.form.get("approved") else 0
        rec.denied   = 1 if request.form.get("denied") else 0
        if rec.denied and not rec.date:
            rec.date = datetime.now().strftime("%Y-%m-%d")
    else:
        rec.allowed = 1 if request.form.get("allowed") else 0

    try:
        db_session.commit()
        flash("✅ Запись обновлена", "success")
    except Exception as e:
        db_session.rollback()
        flash(f"❌ Ошибка: {e}", "error")
    return redirect(url_for("inn_upload"))


@app.post("/inn/del/<string:table>/<int:item_id>")
@login_required
def inn_del(table, item_id):
    if table not in INN_MODELS:
        flash("⚠️ Неверная таблица", "error")
        return redirect(url_for("inn_upload"))
    Model = INN_MODELS[table]
    rec = db_session.get(Model, item_id)
    if rec:
        db_session.delete(rec)
        db_session.commit()
        flash(f"🗑 Запись «{rec.name}» удалена", "success")
    return redirect(url_for("inn_upload"))


@app.post("/inn/toggle/<string:table>/<int:item_id>")
@login_required
def inn_toggle(table, item_id):
    if table not in ("dilers", "lpu"):
        flash("⚠️ Неверная таблица", "error")
        return redirect(url_for("inn_upload"))
    Model = INN_MODELS[table]
    rec = db_session.get(Model, item_id)
    if rec:
        rec.allowed = 0 if rec.allowed else 1
        db_session.commit()
    return redirect(url_for("inn_upload"))


@app.post("/user/save/<int:user_id>")
@login_required
def user_save(user_id: int):
    """Inline-сохранение: модули + флаги is_superuser/active."""
    u = db_session.get(User, user_id)
    if not u:
        flash("Пользователь не найден.", "error")
        return redirect(url_for("upload_file"))

    u.modules = _parse_modules(request.form)
    new_super = 1 if request.form.get("is_superuser") else 0
    new_active = 1 if request.form.get("active") else 0

    if current_user.id == user_id and (not new_super or not new_active):
        flash("Нельзя снять с себя is_superuser или active.", "error")
        return redirect(url_for("upload_file"))

    u.is_superuser = new_super
    u.active = new_active
    db_session.commit()
    flash(f"✅ Настройки пользователя «{u.username or u.full_name or u.tg_id}» сохранены.", "success")
    return redirect(url_for("upload_file"))


@app.post("/user/edit/<int:user_id>")
@login_required
def user_edit(user_id: int):
    """Изменение текстовых полей: username, full_name, title, tg_id."""
    u = db_session.get(User, user_id)
    if not u:
        flash("Пользователь не найден.", "error")
        return redirect(url_for("upload_file"))

    username = (request.form.get("username") or "").strip() or None
    full_name = (request.form.get("full_name") or "").strip() or None
    title     = (request.form.get("title") or "").strip() or None
    tg_id     = _normalize_tg_id(request.form.get("tg_id") or "")
    if tg_id == "INVALID":
        flash("tg_id должен быть числом.", "error")
        return redirect(url_for("upload_file"))

    if username and not re.fullmatch(r'[a-zA-Z0-9_\-]+', username):
        flash("Логин: только латинские буквы, цифры, _ и -", "error")
        return redirect(url_for("upload_file"))

    if username and username != u.username:
        if db_session.query(User).filter_by(username=username).first():
            flash(f"Логин «{username}» уже занят.", "warning")
            return redirect(url_for("upload_file"))
    if tg_id is not None and tg_id != u.tg_id:
        if db_session.query(User).filter_by(tg_id=tg_id).first():
            flash(f"tg_id {tg_id} уже занят.", "warning")
            return redirect(url_for("upload_file"))

    if not username and not tg_id:
        flash("Нельзя оставить пользователя без логина и без tg_id.", "error")
        return redirect(url_for("upload_file"))

    u.username = username
    u.full_name = full_name
    u.title = title
    u.tg_id = tg_id
    db_session.commit()
    flash("✅ Данные обновлены.", "success")
    return redirect(url_for("upload_file"))


@app.post("/user/setpw/<int:user_id>")
@login_required
def user_setpw(user_id: int):
    """Сброс пароля. Если пароль пустой и есть tg_id — снимаем PWA-доступ."""
    u = db_session.get(User, user_id)
    if not u:
        flash("Пользователь не найден.", "error")
        return redirect(url_for("upload_file"))
    password = (request.form.get("password") or "").strip()
    if password:
        u.set_password(password)
        flash(f"✅ Пароль для «{u.username}» обновлён.", "success")
    else:
        if not u.tg_id:
            flash("Нельзя очистить пароль у PWA-only пользователя — он перестанет логиниться.", "error")
            return redirect(url_for("upload_file"))
        u.password_hash = None
        flash(f"PWA-доступ снят, остаётся tg-доступ.", "success")
    db_session.commit()
    return redirect(url_for("upload_file"))


@app.post("/user/del/<int:user_id>")
@login_required
def user_del(user_id: int):
    if current_user.id == user_id:
        flash("Нельзя удалить самого себя.", "error")
        return redirect(url_for("upload_file"))

    u = db_session.get(User, user_id)
    if u:
        label = u.username or u.full_name or f"tg:{u.tg_id}"
        db_session.delete(u)
        db_session.commit()
        flash(f"🗑 Пользователь «{label}» удалён.", "success")
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

    users = db_session.query(User).filter(User.username.isnot(None)).order_by(User.username).all()

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
