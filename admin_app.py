import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, render_template, request, redirect, flash, url_for
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv
from sqlalchemy import func, text

from app.db.base import Base
from app.db.session import db_session
from app.tools.import_csv import load_file
from app.tools.zip_helper import extract_zip

from functools import wraps
from flask import abort

from app.db.models import (
    User, PwaActivity, InnDiler, InnLpu, InnPending, EmailRecipient,
    Organization, OperationReport, OperationReportAudit, OperationReportFile,
    ReportTag,
)
from flask import send_file, abort as flask_abort
from app.db.models_stats import TgUser, Interaction  # noqa: F401  -- регистрируем модели в Base.metadata
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
            "Эта страница доступна только админам.", 403)


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
                flash("❌ Доступ к админ-панели только у админов. "
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
    organizations = db_session.query(Organization).order_by(
        Organization.kind.desc(),  # 'zmed' раньше 'clinic'
        Organization.name,
    ).all()
    return render_template("upload.html", users=users,
                           organizations=organizations)


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
               "clinic_reports", "clinic_stock",
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


def _parse_organization_id(form) -> int | None:
    """Разбирает organization_id из формы. Пустая строка = None (без привязки)."""
    raw = (form.get("organization_id") or "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        return "INVALID"
    org_id = int(raw)
    if not db_session.get(Organization, org_id):
        return "INVALID"
    return org_id


@app.post("/user/add")
@login_required
def user_add():
    username = (request.form.get("username") or "").strip() or None
    password = (request.form.get("password") or "").strip() or None
    tg_id_raw = request.form.get("tg_id") or ""
    full_name = (request.form.get("full_name") or "").strip() or None
    title     = (request.form.get("title") or "").strip() or None
    email     = (request.form.get("email") or "").strip() or None
    is_super  = 1 if request.form.get("is_superuser") else 0
    active    = 1 if request.form.get("active", "1") else 0

    tg_id = _normalize_tg_id(tg_id_raw)
    if tg_id == "INVALID":
        flash("tg_id должен быть числом.", "error")
        return redirect(url_for("upload_file"))

    org_id = _parse_organization_id(request.form)
    if org_id == "INVALID":
        flash("Выбрана неизвестная организация.", "error")
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
             email=email,
             organization_id=org_id,
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
        flash("Нельзя снять с себя права админа или активность.", "error")
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
    email     = (request.form.get("email") or "").strip() or None
    tg_id     = _normalize_tg_id(request.form.get("tg_id") or "")
    if tg_id == "INVALID":
        flash("tg_id должен быть числом.", "error")
        return redirect(url_for("upload_file"))

    org_id = _parse_organization_id(request.form)
    if org_id == "INVALID":
        flash("Выбрана неизвестная организация.", "error")
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
    u.email = email
    u.tg_id = tg_id
    u.organization_id = org_id
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


# ─────────────────────────────
# Организации (клиники + ZMed)

@app.route("/organizations", methods=["GET"])
@login_required
def organizations():
    """Справочник организаций: внутренняя ZMed + клиники.

    Используется для привязки пользователей через поле organization_id —
    это даёт row-level security в клинических модулях.

    Передаёт в шаблон список InnLpu, которые ещё НЕ импортированы
    как Organization — для одношагового создания клиники из справочника.
    """
    items = db_session.query(Organization).order_by(
        Organization.kind.desc(), Organization.name
    ).all()
    user_counts = dict(
        db_session.query(User.organization_id, func.count(User.id))
        .filter(User.organization_id.isnot(None))
        .group_by(User.organization_id).all()
    )
    # Количество отчётов по клиникам (для «архив» помним аудит)
    report_counts = dict(
        db_session.query(OperationReport.organization_id,
                          func.count(OperationReport.id))
        .group_by(OperationReport.organization_id).all()
    )

    active_items  = [o for o in items if o.active]
    archived_items = [o for o in items if not o.active]

    # Неимпортированные ЛПУ — по ИНН и по названию
    existing_inns  = {o.inn for o in items if o.inn}
    existing_names = {o.name for o in items}
    unimported_lpus = [
        l for l in db_session.query(InnLpu).order_by(InnLpu.name).all()
        if (l.inn or "").strip() not in existing_inns
        and (l.name or "").strip() not in existing_names
    ]

    return render_template("organizations.html",
                           organizations=items,
                           active_items=active_items,
                           archived_items=archived_items,
                           user_counts=user_counts,
                           report_counts=report_counts,
                           unimported_lpus=unimported_lpus)


@app.post("/organizations/add")
@login_required
def organization_add():
    name = (request.form.get("name") or "").strip()
    inn  = (request.form.get("inn") or "").strip() or None
    kind = (request.form.get("kind") or "").strip()

    if not name:
        flash("Укажите название организации.", "error")
        return redirect(url_for("organizations"))
    if kind not in ("zmed", "clinic"):
        flash("Тип организации должен быть 'zmed' или 'clinic'.", "error")
        return redirect(url_for("organizations"))
    if db_session.query(Organization).filter_by(name=name).first():
        flash(f"Организация «{name}» уже есть.", "warning")
        return redirect(url_for("organizations"))

    db_session.add(Organization(name=name, inn=inn, kind=kind, active=1))
    db_session.commit()
    flash(f"✅ Организация «{name}» добавлена.", "success")
    return redirect(url_for("organizations"))


@app.post("/organizations/import-from-lpu")
@login_required
def organization_import_from_lpu():
    """Импорт клиники из справочника InnLpu: берём name+inn, kind='clinic'."""
    lpu_id = request.form.get("lpu_id", type=int)
    if not lpu_id:
        flash("Выберите ЛПУ из списка.", "error")
        return redirect(url_for("organizations"))

    lpu = db_session.get(InnLpu, lpu_id)
    if not lpu:
        flash("ЛПУ не найдено.", "error")
        return redirect(url_for("organizations"))

    name = (lpu.name or "").strip()
    inn = (lpu.inn or "").strip() or None
    if not name:
        flash("У выбранного ЛПУ пустое название.", "error")
        return redirect(url_for("organizations"))

    # Защита от дубликатов — и по имени, и по ИНН
    if db_session.query(Organization).filter_by(name=name).first():
        flash(f"Организация «{name}» уже есть.", "warning")
        return redirect(url_for("organizations"))
    if inn and db_session.query(Organization).filter_by(inn=inn).first():
        flash(f"Организация с ИНН {inn} уже есть.", "warning")
        return redirect(url_for("organizations"))

    db_session.add(Organization(name=name, inn=inn, kind="clinic", active=1))
    db_session.commit()
    flash(f"✅ Клиника «{name}» импортирована из справочника ЛПУ.", "success")
    return redirect(url_for("organizations"))


@app.post("/organizations/edit/<int:org_id>")
@login_required
def organization_edit(org_id: int):
    org = db_session.get(Organization, org_id)
    if not org:
        flash("Организация не найдена.", "error")
        return redirect(url_for("organizations"))

    name = (request.form.get("name") or "").strip()
    inn  = (request.form.get("inn") or "").strip() or None
    kind = (request.form.get("kind") or "").strip()
    active = 1 if request.form.get("active") else 0

    if not name:
        flash("Укажите название организации.", "error")
        return redirect(url_for("organizations"))
    if kind not in ("zmed", "clinic"):
        flash("Тип организации должен быть 'zmed' или 'clinic'.", "error")
        return redirect(url_for("organizations"))
    if name != org.name and db_session.query(Organization).filter_by(name=name).first():
        flash(f"Название «{name}» уже занято.", "warning")
        return redirect(url_for("organizations"))

    org.name = name
    org.inn = inn
    org.kind = kind
    org.active = active
    db_session.commit()
    flash("✅ Сохранено.", "success")
    return redirect(url_for("organizations"))


@app.post("/organizations/archive/<int:org_id>")
@login_required
def organization_archive(org_id: int):
    """Архивация клиники (soft-delete).

    Активные юзеры этой клиники потеряют доступ к клиническим модулям
    на уровне require_org_scope (там проверка org.active). ZMed-admin
    по-прежнему видит её данные для аудита.
    """
    org = db_session.get(Organization, org_id)
    if not org:
        flash("Организация не найдена.", "error")
        return redirect(url_for("organizations"))
    if org.kind == "zmed":
        flash("ZMed-организацию нельзя архивировать.", "error")
        return redirect(url_for("organizations"))
    org.active = 0
    db_session.commit()
    flash(f"📦 Клиника «{org.name}» переведена в архив.", "success")
    return redirect(url_for("organizations"))


@app.post("/organizations/restore/<int:org_id>")
@login_required
def organization_restore(org_id: int):
    org = db_session.get(Organization, org_id)
    if not org:
        flash("Организация не найдена.", "error")
        return redirect(url_for("organizations"))
    org.active = 1
    db_session.commit()
    flash(f"✅ Клиника «{org.name}» восстановлена.", "success")
    return redirect(url_for("organizations"))


@app.post("/organizations/del/<int:org_id>")
@login_required
def organization_del(org_id: int):
    org = db_session.get(Organization, org_id)
    if not org:
        flash("Организация не найдена.", "error")
        return redirect(url_for("organizations"))
    linked = db_session.query(User).filter_by(organization_id=org_id).count()
    if linked:
        flash(f"Нельзя удалить «{org.name}» — к ней привязано пользователей: {linked}. "
              "Сначала перепривяжите или удалите их.", "error")
        return redirect(url_for("organizations"))
    name = org.name
    db_session.delete(org)
    db_session.commit()
    flash(f"🗑 Организация «{name}» удалена.", "success")
    return redirect(url_for("organizations"))


# ─────────────────────────────
# Теги отчётов (справочник ZMed)

@app.route("/report-tags", methods=["GET"])
@login_required
def report_tags():
    items = db_session.query(ReportTag).order_by(
        ReportTag.active.desc(), ReportTag.name
    ).all()
    return render_template("report_tags.html", tags=items)


@app.post("/report-tags/add")
@login_required
def report_tag_add():
    name = (request.form.get("name") or "").strip()
    color = (request.form.get("color") or "#9a2a3a").strip()
    descr = (request.form.get("description") or "").strip() or None
    if not name:
        flash("Укажите название тега.", "error")
        return redirect(url_for("report_tags"))
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        flash("Цвет должен быть в формате #RRGGBB.", "error")
        return redirect(url_for("report_tags"))
    if db_session.query(ReportTag).filter_by(name=name).first():
        flash(f"Тег «{name}» уже есть.", "warning")
        return redirect(url_for("report_tags"))
    db_session.add(ReportTag(name=name, color=color, description=descr, active=1))
    db_session.commit()
    flash(f"✅ Тег «{name}» добавлен.", "success")
    return redirect(url_for("report_tags"))


@app.post("/report-tags/edit/<int:tag_id>")
@login_required
def report_tag_edit(tag_id: int):
    t = db_session.get(ReportTag, tag_id)
    if not t:
        flash("Тег не найден.", "error")
        return redirect(url_for("report_tags"))
    name = (request.form.get("name") or "").strip()
    color = (request.form.get("color") or "#9a2a3a").strip()
    descr = (request.form.get("description") or "").strip() or None
    active = 1 if request.form.get("active") else 0
    if not name:
        flash("Укажите название тега.", "error")
        return redirect(url_for("report_tags"))
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        flash("Цвет должен быть в формате #RRGGBB.", "error")
        return redirect(url_for("report_tags"))
    if name != t.name and db_session.query(ReportTag).filter_by(name=name).first():
        flash(f"«{name}» уже занято.", "warning")
        return redirect(url_for("report_tags"))
    t.name = name
    t.color = color
    t.description = descr
    t.active = active
    db_session.commit()
    flash("✅ Сохранено.", "success")
    return redirect(url_for("report_tags"))


@app.post("/report-tags/del/<int:tag_id>")
@login_required
def report_tag_del(tag_id: int):
    t = db_session.get(ReportTag, tag_id)
    if not t:
        flash("Тег не найден.", "error")
        return redirect(url_for("report_tags"))
    name = t.name
    db_session.delete(t)
    db_session.commit()
    flash(f"🗑 Тег «{name}» удалён.", "success")
    return redirect(url_for("report_tags"))


# ─────────────────────────────
# Рассылка заказов: адресаты

@app.route("/email-recipients", methods=["GET"])
@login_required
def email_recipients():
    items = db_session.query(EmailRecipient).order_by(EmailRecipient.email).all()
    return render_template("email_recipients.html", recipients=items)


EMAIL_KINDS = ("all", "orders", "reports")


@app.post("/email-recipients/add")
@login_required
def email_recipient_add():
    email = (request.form.get("email") or "").strip().lower()
    label = (request.form.get("label") or "").strip() or None
    kind  = (request.form.get("kind") or "all").strip()
    if not email or "@" not in email:
        flash("Укажите корректный email.", "error")
        return redirect(url_for("email_recipients"))
    if kind not in EMAIL_KINDS:
        flash("Неверный тип рассылки.", "error")
        return redirect(url_for("email_recipients"))
    if db_session.query(EmailRecipient).filter_by(email=email).first():
        flash(f"Адрес «{email}» уже в списке.", "warning")
        return redirect(url_for("email_recipients"))
    db_session.add(EmailRecipient(email=email, label=label, kind=kind))
    db_session.commit()
    flash(f"✅ Адрес «{email}» добавлен.", "success")
    return redirect(url_for("email_recipients"))


@app.post("/email-recipients/edit/<int:rid>")
@login_required
def email_recipient_edit(rid: int):
    r = db_session.get(EmailRecipient, rid)
    if not r:
        flash("Адрес не найден.", "error")
        return redirect(url_for("email_recipients"))
    new_email = (request.form.get("email") or "").strip().lower()
    new_label = (request.form.get("label") or "").strip() or None
    new_kind  = (request.form.get("kind") or "all").strip()
    if not new_email or "@" not in new_email:
        flash("Укажите корректный email.", "error")
        return redirect(url_for("email_recipients"))
    if new_kind not in EMAIL_KINDS:
        flash("Неверный тип рассылки.", "error")
        return redirect(url_for("email_recipients"))
    if new_email != r.email:
        if db_session.query(EmailRecipient).filter_by(email=new_email).first():
            flash(f"Адрес «{new_email}» уже занят.", "warning")
            return redirect(url_for("email_recipients"))
    r.email = new_email
    r.label = new_label
    r.kind  = new_kind
    db_session.commit()
    flash("✅ Сохранено.", "success")
    return redirect(url_for("email_recipients"))


@app.route("/admin-clinic-reports", methods=["GET"])
@login_required
def admin_clinic_reports():
    """Список отчётов об операциях — админ ZMed видит все клиники."""
    org_id = request.args.get("organization_id", type=int)
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    status_f = request.args.get("status", "")

    q = db_session.query(OperationReport).order_by(
        OperationReport.operation_date.desc(), OperationReport.id.desc()
    )
    if org_id:
        q = q.filter(OperationReport.organization_id == org_id)
    if date_from:
        q = q.filter(OperationReport.operation_date >= date_from)
    if date_to:
        q = q.filter(OperationReport.operation_date <= date_to)
    if status_f:
        q = q.filter(OperationReport.status == status_f)
    reports = q.limit(500).all()

    # file counts
    file_counts = {}
    if reports:
        counts = db_session.query(
            OperationReportFile.report_id, func.count(OperationReportFile.id)
        ).filter(
            OperationReportFile.report_id.in_([r.id for r in reports])
        ).group_by(OperationReportFile.report_id).all()
        file_counts = dict(counts)

    orgs = db_session.query(Organization).filter_by(active=1).order_by(Organization.name).all()
    org_map = {o.id: o for o in orgs}
    users = {u.id: u for u in db_session.query(User).filter(
        User.id.in_({r.user_id for r in reports} or {0})
    ).all()}

    return render_template(
        "admin_clinic_reports.html",
        reports=reports,
        orgs=orgs, org_map=org_map, users=users,
        file_counts=file_counts,
        filters={"organization_id": org_id, "date_from": date_from,
                 "date_to": date_to, "status": status_f},
    )


@app.route("/admin-clinic-reports/<int:report_id>", methods=["GET"])
@login_required
def admin_clinic_report_detail(report_id: int):
    r = db_session.get(OperationReport, report_id)
    if not r:
        flash("Отчёт не найден.", "error")
        return redirect(url_for("admin_clinic_reports"))

    org = db_session.get(Organization, r.organization_id)
    user = db_session.get(User, r.user_id)
    files = db_session.query(OperationReportFile).filter_by(report_id=report_id).all()
    audit_entries = db_session.query(OperationReportAudit).filter_by(
        report_id=report_id
    ).order_by(OperationReportAudit.id.desc()).all()
    audit_users = {u.id: u for u in db_session.query(User).filter(
        User.id.in_({a.user_id for a in audit_entries} or {0})
    ).all()}

    implants = []
    if r.implants_used_json:
        try:
            implants = json.loads(r.implants_used_json)
        except (ValueError, TypeError):
            implants = []

    return render_template(
        "admin_clinic_report_detail.html",
        r=r, org=org, user=user, files=files, implants=implants,
        audit=audit_entries, audit_users=audit_users,
    )


@app.route("/admin-clinic-reports/<int:report_id>/files/<int:file_id>")
@login_required
def admin_clinic_report_file(report_id: int, file_id: int):
    """Отдаёт файл отчёта. Доступ — любому админу (is_superuser проверен глобально)."""
    rec = db_session.get(OperationReportFile, file_id)
    if not rec or rec.report_id != report_id:
        flask_abort(404)
    data_dir = os.getenv("REPORTS_DIR") or os.path.join(
        os.path.dirname(__file__), "data", "reports"
    )
    base = Path(data_dir).resolve()

    # Защита от path-traversal в stored_path
    p = Path(rec.stored_path)
    if p.is_absolute() or ".." in p.parts:
        flask_abort(400)
    disk_path = (base / p).resolve()
    try:
        disk_path.relative_to(base)
    except ValueError:
        flask_abort(400)

    if not disk_path.exists():
        flask_abort(410)
    return send_file(
        str(disk_path),
        mimetype=rec.content_type or "application/octet-stream",
        as_attachment=False,
        download_name=rec.original_name or f"file_{rec.id}",
    )


@app.post("/email-recipients/del/<int:rid>")
@login_required
def email_recipient_del(rid: int):
    r = db_session.get(EmailRecipient, rid)
    if r:
        email = r.email
        db_session.delete(r)
        db_session.commit()
        flash(f"🗑 Адрес «{email}» удалён.", "success")
    else:
        flash("Адрес не найден.", "error")
    return redirect(url_for("email_recipients"))


ACTION_LABELS = {
    "login":                   "Вход",
    "search":                  "Поиск",
    "pdf_export":              "Экспорт PDF",
    "add_to_cart":             "В корзину",
    "place_order":             "Заказ",
    "inn_check":               "Проверка ИНН",
    "clinic_report_create":    "Отчёт создан",
    "clinic_report_update":    "Отчёт изменён",
    "clinic_stock_receive":    "ОХ: приход",
    "clinic_stock_transfer":   "ОХ: перемещение",
    "clinic_stock_consume":    "ОХ: расход",
    "clinic_stock_return":     "ОХ: возврат",
    "clinic_stock_inventory":  "ОХ: инвент.",
    "clinic_stock_write_off":  "ОХ: списание",
}

ACTION_COLORS = {
    "login":                   "primary",
    "search":                  "success",
    "pdf_export":              "warning",
    "add_to_cart":             "info",
    "place_order":             "danger",
    "inn_check":               "secondary",
    "clinic_report_create":    "info",
    "clinic_report_update":    "info",
    "clinic_stock_receive":    "success",
    "clinic_stock_transfer":   "primary",
    "clinic_stock_consume":    "warning",
    "clinic_stock_return":     "info",
    "clinic_stock_inventory":  "secondary",
    "clinic_stock_write_off":  "danger",
}


MODULE_LABELS = {
    "implants":       "Импланты",
    "implants_view":  "Импланты (просмотр)",
    "supplies":       "Расходники",
    "clinic_reports": "Отчёты клиник",
    "clinic_stock":   "Учёт ОХ",
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
    if action in ("clinic_report_create", "clinic_report_update"):
        parts = [f"Отчёт #{detail.get('report_id')}"]
        if detail.get("status"):
            parts.append(detail["status"])
        if detail.get("organization_id"):
            parts.append(f"ЛПУ#{detail['organization_id']}")
        return " | ".join(parts)
    if action.startswith("clinic_stock_"):
        qty = detail.get("qty") or detail.get("delta")
        parts = [f"item#{detail.get('item_id')}"]
        if qty is not None:
            parts.append(f"× {qty}")
        for k in ("from", "to", "location_id", "report_id"):
            if detail.get(k):
                parts.append(f"{k}={detail[k]}")
        return " | ".join(parts)
    return "—"


MODULE_DISPLAY = {
    "implants":       ("⚕️ Импланты (заказ)",     "primary"),
    "implants_view":  ("⚕️ Импланты (просмотр)",  "info"),
    "supplies":       ("🔧 Расходники",            "success"),
    "inn_check":      ("🔍 Проверка ИНН",          "secondary"),
    "clinic_reports": ("📋 Отчёты клиник",         "danger"),
    "clinic_stock":   ("📦 Учёт ОХ",               "warning"),
    "login":          ("🔑 Входы",                 "dark"),
}


def _activity_module(action: str, detail: dict) -> str:
    """Определяет модуль по действию и detail."""
    if action == "login":
        return "login"
    if action in ("add_to_cart", "place_order"):
        return "implants"
    if action == "inn_check":
        return "inn_check"
    if action.startswith("clinic_report"):
        return "clinic_reports"
    if action.startswith("clinic_stock"):
        return "clinic_stock"
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


BOT_LABELS = {
    "stockbot2":          "Расходники",
    "stockbot2_implants": "Импланты",
    "flask_bot_app":      "ИНН",
}
BOT_COLORS = {
    "stockbot2":          "success",
    "stockbot2_implants": "primary",
    "flask_bot_app":      "secondary",
}
KIND_LABELS = {
    "start":    "🚀 /start",
    "command":  "⚙️ команда",
    "message":  "💬 сообщение",
    "callback": "🔘 кнопка",
}
KIND_COLORS = {
    "start":    "success",
    "command":  "info",
    "message":  "primary",
    "callback": "warning",
}
PIVOT_KINDS = ["start", "command", "message", "callback"]


@app.route("/tg-stats")
@login_required
def tg_stats():
    date_from_str = request.args.get("date_from", "")
    date_to_str   = request.args.get("date_to", "")
    bot_filter    = request.args.get("bot_name", "")
    tg_id_filter  = request.args.get("tg_id", type=int)

    today = datetime.utcnow().date()
    if not (date_from_str or date_to_str):
        date_from_str = (today - timedelta(days=30)).strftime("%Y-%m-%d")
        date_to_str = today.strftime("%Y-%m-%d")
    period_set = bool(date_from_str or date_to_str)

    where = []
    params = {}
    if date_from_str:
        where.append("i.created_at >= :df")
        params["df"] = datetime.strptime(date_from_str, "%Y-%m-%d")
    if date_to_str:
        where.append("i.created_at < :dt")
        params["dt"] = datetime.strptime(date_to_str, "%Y-%m-%d") + timedelta(days=1)
    if bot_filter:
        where.append("i.bot_name = :bn")
        params["bn"] = bot_filter
    if tg_id_filter:
        where.append("i.user_id = :tg")
        params["tg"] = tg_id_filter
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    # ── Сводная 1: боты × типы событий ────────────────────────────────────
    pivot_rows = db_session.execute(text(f"""
        SELECT i.bot_name, i.kind, COUNT(*) AS cnt
        FROM tg_interactions i
        {where_sql}
        GROUP BY i.bot_name, i.kind
    """), params).all()
    pivot: dict[str, dict[str, int]] = {}
    for bn, kind, cnt in pivot_rows:
        pivot.setdefault(bn, {})[kind] = cnt

    # ── Сводная 2: топ-10 юзеров (с разбивкой по ботам) ───────────────────
    top_rows = db_session.execute(text(f"""
        SELECT i.user_id AS tg_id, i.bot_name, COUNT(*) AS cnt
        FROM tg_interactions i
        {where_sql}
        GROUP BY i.user_id, i.bot_name
    """), params).all()
    by_user: dict[int, dict] = {}
    for tg_id, bn, cnt in top_rows:
        d = by_user.setdefault(tg_id, {"_total": 0})
        d[bn] = cnt
        d["_total"] += cnt
    top_ids = sorted(by_user, key=lambda k: -by_user[k]["_total"])[:10]

    name_map = {}
    if top_ids:
        placeholders = ",".join(f":id{i}" for i in range(len(top_ids)))
        name_params = {f"id{i}": tg_id for i, tg_id in enumerate(top_ids)}
        name_rows = db_session.execute(text(f"""
            SELECT
                tu.id AS tg_id,
                COALESCE(
                    u.full_name,
                    NULLIF(TRIM(COALESCE(tu.first_name,'') || ' ' || COALESCE(tu.last_name,'')), ''),
                    tu.username
                ) AS display_name,
                u.title AS title,
                u.username AS pwa_username
            FROM tg_users tu
            LEFT JOIN users u ON u.tg_id = tu.id
            WHERE tu.id IN ({placeholders})
        """), name_params).all()
        for tg_id, display_name, title, pwa_username in name_rows:
            name_map[tg_id] = {
                "display": display_name or f"tg:{tg_id}",
                "title": title,
                "pwa_username": pwa_username,
            }

    top_users = []
    for tg_id in top_ids:
        info = name_map.get(tg_id, {"display": f"tg:{tg_id}", "title": None, "pwa_username": None})
        top_users.append({
            "tg_id":         tg_id,
            "display":       info["display"],
            "title":         info["title"],
            "pwa_username":  info["pwa_username"],
            "counts":        {k: v for k, v in by_user[tg_id].items() if k != "_total"},
            "total":         by_user[tg_id]["_total"],
        })

    # ── Журнал событий ────────────────────────────────────────────────────
    journal_rows = db_session.execute(text(f"""
        SELECT
            i.id, i.created_at, i.bot_name, i.kind, i.payload,
            i.user_id AS tg_id,
            COALESCE(
                u.full_name,
                NULLIF(TRIM(COALESCE(tu.first_name,'') || ' ' || COALESCE(tu.last_name,'')), ''),
                tu.username
            ) AS display_name,
            u.title AS title
        FROM tg_interactions i
        LEFT JOIN tg_users tu ON tu.id = i.user_id
        LEFT JOIN users u ON u.tg_id = i.user_id
        {where_sql}
        ORDER BY i.created_at DESC
        LIMIT 1000
    """), params).all()
    def _parse_dt(v):
        if v is None or isinstance(v, datetime):
            return v
        try:
            return datetime.fromisoformat(v)
        except (ValueError, TypeError):
            return None

    interactions = [{
        "id":           r.id,
        "created_at":   _parse_dt(r.created_at),
        "bot_name":     r.bot_name,
        "kind":         r.kind,
        "payload":      r.payload,
        "tg_id":        r.tg_id,
        "display_name": r.display_name or f"tg:{r.tg_id}",
        "title":        r.title,
    } for r in journal_rows]

    # Справочники для фильтров (по всей истории, не ограниченной фильтром)
    all_bots = [r[0] for r in db_session.execute(
        text("SELECT DISTINCT bot_name FROM tg_interactions ORDER BY bot_name")
    ).all()]

    all_users = db_session.execute(text("""
        SELECT DISTINCT
            i.user_id AS tg_id,
            COALESCE(
                u.full_name,
                NULLIF(TRIM(COALESCE(tu.first_name,'') || ' ' || COALESCE(tu.last_name,'')), ''),
                tu.username
            ) AS display_name
        FROM tg_interactions i
        LEFT JOIN tg_users tu ON tu.id = i.user_id
        LEFT JOIN users u ON u.tg_id = i.user_id
        ORDER BY display_name
    """)).all()
    all_users = [(tg_id, display or f"tg:{tg_id}") for tg_id, display in all_users]

    return render_template(
        "tg_stats.html",
        pivot=pivot,
        pivot_kinds=PIVOT_KINDS,
        top_users=top_users,
        interactions=interactions,
        all_bots=all_bots,
        all_users=all_users,
        bot_labels=BOT_LABELS,
        bot_colors=BOT_COLORS,
        kind_labels=KIND_LABELS,
        kind_colors=KIND_COLORS,
        period_set=period_set,
        filters={
            "date_from": date_from_str,
            "date_to":   date_to_str,
            "bot_name":  bot_filter,
            "tg_id":     tg_id_filter or "",
        },
    )


if __name__ == "__main__":
    with app.app_context():
        create_admin_user()

    app.run(host="0.0.0.0", port=5102)
