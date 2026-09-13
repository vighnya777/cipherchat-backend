from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_socketio import emit

from cipherchat.admin import services as admin_svc
from cipherchat.config import get_config
from cipherchat.services.storage import store

admin_bp = Blueprint("admin", __name__)


def _require_admin():
    if admin_svc.is_authenticated_admin():
        return True
    from flask import session
    if session.get("authenticated"):
        flash("Admin access required for this account.", "error")
        return "forbidden"
    flash("Please sign in with an admin account.", "error")
    return False


@admin_bp.route("/admin")
@admin_bp.route("/admin/")
def admin():
    status = _require_admin()
    if status is not True:
        if status == "forbidden":
            flash("This account is not an admin. Set role=admin or ADMIN_EMAIL in .env.", "error")
            return redirect(url_for("chat.chat"))
        return redirect(url_for("auth.login", next="/admin"))

    try:
        admin_svc.ensure_admin_user()
        search_query = request.args.get("q", "")
        status_filter = request.args.get("status", "")
        role_filter = request.args.get("role", "")
        sort_by = request.args.get("sort", "username")
        sort_order = request.args.get("order", "asc")

        stats = admin_svc.calculate_admin_stats()
        users = admin_svc.filter_users(
            query=search_query,
            status_filter=status_filter,
            role_filter=role_filter,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        logs = admin_svc.get_recent_logs(100)
        active_users = getattr(store, "active_users", {}) or {}
        return render_template(
            "admin/dashboard.html",
            stats=stats or {},
            users=users or [],
            logs=logs or [],
            active_users=active_users,
            search_query=search_query,
            status_filter=status_filter,
            role_filter=role_filter,
            sort_by=sort_by,
            sort_order=sort_order,
            admin_email=get_config().ADMIN_EMAIL,
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Admin dashboard failed")
        return (
            f"<h1>Admin error</h1><pre>{exc}</pre><p><a href='/chat'>Back to chat</a></p>",
            500,
        )


@admin_bp.route("/admin/dashboard")
def admin_dashboard():
    return redirect(url_for("admin.admin"))


@admin_bp.route("/admin/api/stats")
def admin_api_stats():
    if not admin_svc.is_authenticated_admin():
        return jsonify({"error": "unauthorized"}), 403
    return jsonify(admin_svc.calculate_admin_stats())


@admin_bp.route("/admin/api/update_role", methods=["POST"])
def admin_api_update_role():
    if not admin_svc.is_authenticated_admin():
        return jsonify({"error": "unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    role = data.get("role")
    if not email or not role:
        return jsonify({"error": "missing fields"}), 400
    ok = admin_svc.update_user_data(email, {"role": role})
    admin_svc.log_admin_action("update_role", {"email": email, "role": role})
    return jsonify({"success": ok})


@admin_bp.route("/admin/api/bulk_action", methods=["POST"])
def admin_api_bulk_action():
    if not admin_svc.is_authenticated_admin():
        return jsonify({"error": "unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    emails = data.get("emails") or []
    action = data.get("action")
    count = admin_svc.perform_bulk_action(emails, action)
    admin_svc.log_admin_action("bulk_action", {"action": action, "count": count})
    return jsonify({"success": True, "count": count})


@admin_bp.route("/admin/api/system/health")
def admin_api_system_health():
    if not admin_svc.is_authenticated_admin():
        return jsonify({"error": "unauthorized"}), 403
    return jsonify(admin_svc.get_system_health_info())


@admin_bp.route("/admin/api/broadcast", methods=["POST"])
def admin_api_broadcast():
    if not admin_svc.is_authenticated_admin():
        return jsonify({"error": "unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    from cipherchat.extensions import socketio
    socketio.emit(
        "admin_broadcast",
        {
            "message": message,
            "from": "admin",
            "timestamp": __import__("datetime").datetime.now().isoformat(),
        },
    )
    admin_svc.log_admin_action("broadcast", message[:200])
    return jsonify({"success": True})


@admin_bp.route("/admin/api/user/<email>")
def admin_api_user_detail(email):
    if not admin_svc.is_authenticated_admin():
        return jsonify({"error": "unauthorized"}), 403
    user = store.users.get(email)
    if not user:
        return jsonify({"error": "not found"}), 404
    return jsonify(admin_svc.get_detailed_user_info(email, user))


@admin_bp.route("/admin/api/users/<email>/update", methods=["POST"])
def admin_api_update_user(email):
    if not admin_svc.is_authenticated_admin():
        return jsonify({"error": "unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    ok = admin_svc.update_user_data(email, data)
    return jsonify({"success": ok})


@admin_bp.route("/admin/api/logs/clear", methods=["POST"])
def admin_api_clear_logs():
    if not admin_svc.is_authenticated_admin():
        return jsonify({"error": "unauthorized"}), 403
    n = admin_svc.clear_activity_logs()
    return jsonify({"success": True, "cleared": n})


@admin_bp.route("/admin/api/rooms/cleanup", methods=["POST"])
def admin_api_cleanup_rooms():
    if not admin_svc.is_authenticated_admin():
        return jsonify({"error": "unauthorized"}), 403
    n = admin_svc.cleanup_old_rooms()
    return jsonify({"success": True, "removed": n})


@admin_bp.route("/admin/pending")
def admin_pending():
    return redirect(url_for("admin.admin", status="pending"))


@admin_bp.route("/admin/approve", methods=["GET", "POST"])
def admin_approve():
    if request.method == "GET":
        return redirect(url_for("admin.admin", status="pending"))
    status = _require_admin()
    if status is not True:
        return redirect(url_for("auth.login", next="/admin") if status is False else url_for("chat.chat"))
    email = request.form.get("email", "").strip()
    if admin_svc.approve_user(email):
        flash(f"User {email} approved.", "success")
    else:
        flash("User not found.", "error")
    return redirect(url_for("admin.admin"))


@admin_bp.route("/admin/reject", methods=["GET", "POST"])
def admin_reject():
    status = _require_admin()
    if status is not True:
        return redirect(url_for("auth.login", next="/admin") if status is False else url_for("chat.chat"))
    email = request.form.get("email", "").strip()
    if admin_svc.reject_user(email):
        flash(f"User {email} rejected.", "warning")
    else:
        flash("User not found.", "error")
    return redirect(url_for("admin.admin"))
