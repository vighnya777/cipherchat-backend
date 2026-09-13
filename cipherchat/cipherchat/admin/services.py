from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import session

from cipherchat.config import get_config
from cipherchat.services.email import send_email
from cipherchat.services import storage as _storage_mod
from cipherchat.services.storage import store


def _S():
    from cipherchat.services import storage as storage_mod
    s = getattr(storage_mod, "store", None)
    if s is None or isinstance(s, dict) or not hasattr(s, "set_user"):
        Storage = getattr(storage_mod, "Storage", None)
        if Storage is not None:
            try:
                s = Storage()
                storage_mod.store = s
            except Exception:
                pass
    if s is None:
        class _Empty:
            users = {}
            active_users = {}
            chat_rooms = {}
            private_rooms = {}
            activity_logs = []
            username_index = {}
            def set_user(self, email, data):
                self.users[email] = data
        s = _Empty()
        try:
            storage_mod.store = s
        except Exception:
            pass
    for name, default in (
        ("active_users", {}),
        ("chat_rooms", {}),
        ("private_rooms", {}),
        ("activity_logs", []),
        ("username_index", {}),
        ("rate_limits", {}),
    ):
        val = getattr(s, name, None)
        if val is None:
            try:
                setattr(s, name, default if not isinstance(default, list) else [])
            except Exception:
                pass
    return s


def _safe_users_items():
    """Return (email, user_dict) pairs regardless of how store.users is shaped."""
    s = _S()
    users_attr = getattr(s, "users", None)
    if users_attr is None:
        return []
    if isinstance(users_attr, list):
        result = []
        for item in users_attr:
            if isinstance(item, dict):
                email = item.get("email", "")
                result.append((email, item))
        return result
    try:
        raw = users_attr.items() if hasattr(users_attr, "items") else []
        return list(raw)
    except Exception:
        return []


def is_authenticated_admin() -> bool:
    from flask import has_request_context
    if not has_request_context() or not session.get("authenticated"):
        return False
    cfg = get_config()
    email = (session.get("user_email") or "").strip().lower()
    username = (session.get("username") or "").strip().lower()
    admin_email = (cfg.ADMIN_EMAIL or "").strip().lower()
    if email and admin_email and email == admin_email:
        return True
    if session.get("role") == "admin" or username == "admin":
        return True
    users_attr = getattr(_S(), "users", {})
    user = None
    if hasattr(users_attr, "get"):
        user = users_attr.get(email) or users_attr.get(session.get("user_email") or "")
    if not user:
        for k, v in _safe_users_items():
            if (k or "").lower() == email:
                user = v
                break
    if user and isinstance(user, dict) and (
        user.get("role") == "admin" or (user.get("username") or "").lower() == "admin"
    ):
        return True
    return False


def ensure_admin_user() -> None:
    cfg = get_config()
    admin_email = cfg.ADMIN_EMAIL
    admin_username = "admin"
    users_attr = getattr(_S(), "users", {})
    exists = (admin_email in users_attr) if hasattr(users_attr, "__contains__") else False
    if not exists:
        _S().set_user(
            admin_email,
            {
                "username": admin_username,
                "status": "approved",
                "verified": True,
                "role": "admin",
                "created_at": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "profile": {"avatar": None, "bio": "System Administrator"},
                "password_hash": None,
                "login_count": 0,
                "last_login": datetime.now().isoformat(),
                "permissions": ["all"],
            },
        )
    else:
        data = users_attr[admin_email] if hasattr(users_attr, "__getitem__") else {}
        if isinstance(data, dict):
            data.update({"username": admin_username, "status": "approved", "verified": True, "role": "admin", "permissions": ["all"]})
        s = _S()
        if hasattr(s, "username_index"):
            s.username_index[admin_username] = admin_email


def get_user_sort_value(user: dict, sort_by: str):
    if sort_by == "username":
        return (user.get("username") or "").lower()
    if sort_by == "created_at":
        return user.get("created_at") or ""
    if sort_by == "last_login":
        return user.get("last_login") or ""
    if sort_by == "login_count":
        return user.get("login_count") or 0
    return (user.get("username") or "").lower()


def filter_users(
    query: str = "",
    status_filter: str = "",
    role_filter: str = "",
    sort_by: str = "username",
    sort_order: str = "asc",
) -> List[dict]:
    results = []
    q = (query or "").lower().strip()
    for email, user in _safe_users_items():
        if not isinstance(user, dict):
            continue
        if status_filter and user.get("status") != status_filter:
            continue
        if role_filter and user.get("role") != role_filter:
            continue
        if q:
            hay = f"{email} {user.get('username', '')} {user.get('role', '')}".lower()
            if q not in hay:
                continue
        row = dict(user)
        row["email"] = email
        results.append(row)
    reverse = sort_order == "desc"
    results.sort(key=lambda u: get_user_sort_value(u, sort_by), reverse=reverse)
    return results


def calculate_admin_stats() -> dict:
    items = _safe_users_items()
    total = len(items)
    approved = pending = rejected = verified = new_this_week = 0
    one_week_ago = (datetime.now() - timedelta(days=7)).isoformat()

    for _email, u in items:
        if not isinstance(u, dict):
            continue
        st = u.get("status")
        if st == "approved":
            approved += 1
        elif st == "pending":
            pending += 1
        elif st == "rejected":
            rejected += 1
        if u.get("verified"):
            verified += 1
        if (u.get("created_at") or "") >= one_week_ago:
            new_this_week += 1

    s = _S()
    active = getattr(s, "active_users", {}) or {}
    try:
        online = len({
            info.get("email")
            for info in active.values()
            if isinstance(info, dict) and info.get("email")
        })
    except Exception:
        online = 0

    chat_rooms = getattr(s, "chat_rooms", {}) or {}
    private_rooms = getattr(s, "private_rooms", {}) or {}
    try:
        total_rooms = len(chat_rooms) + len(private_rooms)
    except Exception:
        total_rooms = 0

    total_messages = 0
    try:
        for m in getattr(chat_rooms, "values", lambda: [])():
            try:
                total_messages += len(m)
            except Exception:
                pass
        for r in getattr(private_rooms, "values", lambda: [])():
            if isinstance(r, dict):
                try:
                    total_messages += len(r.get("messages") or [])
                except Exception:
                    pass
    except Exception:
        pass

    logs = getattr(s, "activity_logs", []) or []
    if not isinstance(logs, list):
        logs = []
    log_count = len(logs)

    recent_logins = sum(
        1 for log in logs
        if isinstance(log, dict) and log.get("action") in ("login_success", "otp_sent")
    )

    if total == 0:
        health = "idle"
    elif recent_logins / max(total, 1) > 0.5:
        health = "healthy"
    elif recent_logins / max(total, 1) > 0.1:
        health = "moderate"
    else:
        health = "low-activity"

    return {
        "total_users": total,
        "approved_users": approved,
        "pending_users": pending,
        "rejected_users": rejected,
        "verified_users": verified,
        "active_users": online,
        "online_users": online,
        "new_users": new_this_week,
        "total_rooms": total_rooms,
        "total_messages": total_messages,
        "activity_log_count": log_count,
        "system_health": health,
        "uptime": "n/a (in-memory)",
    }


def get_detailed_user_info(email: str, user: dict) -> dict:
    info = dict(user)
    info["email"] = email
    info["current_rooms"] = get_user_current_rooms(email)
    return info


def update_user_data(email: str, data: dict) -> bool:
    s = _S()
    email_clean = (email or "").strip().lower()
    if not email_clean:
        return False
    resolved = getattr(s, "resolve_email", lambda x: None)(email_clean)
    target_email = resolved or email_clean
    user = getattr(s, "users", {}).get(target_email)
    if not user or not isinstance(user, dict):
        return False
    user = dict(user)
    allowed = {"status", "role", "verified", "permissions", "profile", "username"}
    for key, value in data.items():
        if key in allowed:
            user[key] = value
    if hasattr(s, "set_user"):
        s.set_user(target_email, user)
    elif hasattr(getattr(s, "users", None), "__setitem__"):
        s.users[target_email] = user
    return True


def perform_bulk_action(user_emails: List[str], action: str) -> int:
    s = _S()
    count = 0
    for raw_email in user_emails:
        email_clean = (raw_email or "").strip().lower()
        if not email_clean:
            continue
        resolved = getattr(s, "resolve_email", lambda x: None)(email_clean)
        target_email = resolved or email_clean
        user = getattr(s, "users", {}).get(target_email)
        if not user or not isinstance(user, dict):
            continue
        user = dict(user)
        if action == "approve":
            user["status"] = "approved"
            user["verified"] = True
            if hasattr(s, "set_user"):
                s.set_user(target_email, user)
            elif hasattr(getattr(s, "users", None), "__setitem__"):
                s.users[target_email] = user
            try:
                send_email(
                    target_email,
                    "Registration Approved",
                    "<p>Your CipherChat account has been approved. You can now sign in.</p>",
                )
            except Exception:
                pass
            count += 1
        elif action == "reject":
            user["status"] = "rejected"
            if hasattr(s, "set_user"):
                s.set_user(target_email, user)
            elif hasattr(getattr(s, "users", None), "__setitem__"):
                s.users[target_email] = user
            try:
                send_email(
                    target_email,
                    "Registration Rejected",
                    "<p>Your registration was rejected. Contact support if you believe this is a mistake.</p>",
                )
            except Exception:
                pass
            count += 1
        elif action == "delete":
            if hasattr(s, "delete_user"):
                s.delete_user(target_email)
            else:
                users_attr = getattr(s, "users", {})
                if hasattr(users_attr, "pop"):
                    users_attr.pop(target_email, None)
                idx = getattr(s, "username_index", {})
                for uname, em in list(idx.items()):
                    if (em or "").strip().lower() == target_email:
                        idx.pop(uname, None)
            count += 1
    return count


def clear_activity_logs() -> int:
    s = _S()
    logs = getattr(s, "activity_logs", None)
    if not isinstance(logs, list):
        return 0
    try:
        n = len(logs)
        logs.clear()
        return n
    except Exception:
        return 0


def cleanup_old_rooms(days_old: int = 30) -> int:
    removed = 0
    s = _S()
    chat_rooms = getattr(s, "chat_rooms", {}) or {}
    for room in list(chat_rooms.keys()):
        if not chat_rooms[room]:
            del chat_rooms[room]
            removed += 1
    return removed


def get_system_health_info() -> dict:
    stats = calculate_admin_stats()
    s = _S()
    logs = getattr(s, "activity_logs", []) or []
    if not isinstance(logs, list):
        logs = []
    recent = [
        log for log in logs
        if isinstance(log, dict) and log.get("action") in ("login_success", "otp_sent")
    ]
    return {**stats, "recent_activity": recent[-20:]}


def get_user_current_rooms(email: str) -> List[str]:
    rooms: List[str] = []
    s = _S()
    active = getattr(s, "active_users", {}) or {}
    if not isinstance(active, dict):
        return rooms
    for _sid, info in list(active.items()):
        if not isinstance(info, dict):
            continue
        if info.get("email") == email:
            rooms.extend(info.get("rooms") or [])
            rooms.extend(info.get("private_rooms") or [])
    return list(dict.fromkeys(rooms))


def get_recent_logs(limit: int = 100, since=None) -> List[dict]:
    s = _S()
    logs = getattr(s, "activity_logs", []) or []
    if not isinstance(logs, list):
        logs = []
    data = list(logs)
    if since is not None:
        data = [
            log for log in data
            if isinstance(log, dict) and (log.get("timestamp") or "") >= since
        ]
    return data[-limit:]


def log_admin_action(action: str, details: Any) -> None:
    from flask import has_request_context
    actor = session.get("user_email", "admin") if has_request_context() else "admin"
    s = _S()
    logs = getattr(s, "activity_logs", None)
    if isinstance(logs, list):
        logs.append({
            "email": actor,
            "action": f"admin:{action}",
            "timestamp": datetime.now().isoformat(),
            "details": details,
            "ip": "",
            "user_agent": "admin",
        })


def approve_user(email: str) -> bool:
    s = _S()
    email_clean = (email or "").strip().lower()
    if not email_clean:
        return False
    resolved = getattr(s, "resolve_email", lambda x: None)(email_clean)
    target_email = resolved or email_clean
    user = getattr(s, "users", {}).get(target_email)
    if not user or not isinstance(user, dict):
        return False
    user = dict(user)
    user["status"] = "approved"
    user["verified"] = True
    if hasattr(s, "set_user"):
        s.set_user(target_email, user)
    elif hasattr(getattr(s, "users", None), "__setitem__"):
        s.users[target_email] = user
    try:
        send_email(
            target_email,
            "Registration Approved",
            "<p>Your CipherChat account has been approved. You can now sign in.</p>",
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to send approval email to %s: %s", target_email, e)
    log_admin_action("approve", target_email)
    return True


def reject_user(email: str) -> bool:
    s = _S()
    email_clean = (email or "").strip().lower()
    if not email_clean:
        return False
    resolved = getattr(s, "resolve_email", lambda x: None)(email_clean)
    target_email = resolved or email_clean
    user = getattr(s, "users", {}).get(target_email)
    if not user or not isinstance(user, dict):
        return False
    user = dict(user)
    user["status"] = "rejected"
    if hasattr(s, "set_user"):
        s.set_user(target_email, user)
    elif hasattr(getattr(s, "users", None), "__setitem__"):
        s.users[target_email] = user
    try:
        send_email(
            target_email,
            "Registration Rejected",
            "<p>Your registration was rejected. Contact support if you believe this is a mistake.</p>",
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to send rejection email to %s: %s", target_email, e)
    log_admin_action("reject", target_email)
    return True



#http://127.0.0.1:5000/login