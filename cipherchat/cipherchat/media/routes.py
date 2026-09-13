"""Media upload / download routes – hardened against path traversal and abuse."""

from __future__ import annotations

import os
import re
import uuid

from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
    send_from_directory,
    session,
    abort,
)
from werkzeug.utils import secure_filename

from cipherchat.config import get_config

media_bp = Blueprint("media", __name__)

# Block double extensions like file.php.jpg when last is allowed? we only check final ext.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _allowed_file(filename: str) -> bool:
    cfg = get_config()
    if not filename or "." not in filename:
        return False
    # Reject path components
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    allowed = (
        cfg.ALLOWED_IMAGE_EXTENSIONS
        | cfg.ALLOWED_VIDEO_EXTENSIONS
        | cfg.ALLOWED_DOCUMENT_EXTENSIONS
        | cfg.ALLOWED_AUDIO_EXTENSIONS
    )
    return ext in allowed


def _safe_stored_name(original: str) -> str:
    base = secure_filename(original) or "file"
    # Strip any remaining unsafe chars
    base = "".join(c for c in base if c.isalnum() or c in "._-")[:100] or "file"
    return f"{uuid.uuid4().hex[:12]}_{base}"


@media_bp.route("/upload", methods=["POST"])
def upload_file():
    if not session.get("authenticated"):
        return jsonify({"error": "unauthorized"}), 401
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "empty filename"}), 400
    if not _allowed_file(f.filename):
        return jsonify({"error": "file type not allowed"}), 400

    # Size: Flask MAX_CONTENT_LENGTH is global; also check Content-Length if present
    cfg = get_config()
    cl = request.content_length
    if cl is not None and cl > cfg.MAX_CONTENT_LENGTH:
        return jsonify({"error": "file too large"}), 413

    unique = _safe_stored_name(f.filename)
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, unique)

    # Ensure resolved path stays inside upload dir
    if not os.path.abspath(path).startswith(os.path.abspath(upload_dir) + os.sep):
        return jsonify({"error": "invalid path"}), 400

    f.save(path)

    original = secure_filename(f.filename) or unique
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext in cfg.ALLOWED_IMAGE_EXTENSIONS:
        ftype = "image"
    elif ext in cfg.ALLOWED_VIDEO_EXTENSIONS:
        ftype = "video"
    elif ext in cfg.ALLOWED_AUDIO_EXTENSIONS:
        ftype = "audio"
    else:
        ftype = "document"

    return jsonify(
        {
            "success": True,
            "url": f"/uploads/{unique}",
            "name": original,
            "type": ftype,
        }
    )


@media_bp.route("/uploads/<path:filename>")
def uploaded_file(filename: str):
    """Serve uploaded files only to authenticated users; block path traversal."""
    if not session.get("authenticated"):
        abort(401)

    # Reject any path traversal attempts
    if not filename or ".." in filename or filename.startswith(("/", "\\")):
        abort(400)
    # Only allow our generated safe names
    base = os.path.basename(filename)
    if base != filename or not _SAFE_NAME.match(base):
        abort(400)

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    full = os.path.join(upload_dir, base)
    if not os.path.abspath(full).startswith(os.path.abspath(upload_dir) + os.sep):
        abort(400)
    if not os.path.isfile(full):
        abort(404)

    return send_from_directory(upload_dir, base)
