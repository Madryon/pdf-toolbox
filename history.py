from pathlib import Path

from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from models import FileHistory, db


history_bp = Blueprint("history", __name__, url_prefix="/history")


def create_history_entry(tool_name: str, output_name: str, output_path: str) -> None:
    if not current_user.is_authenticated:
        return
    item = FileHistory(
        user_id=current_user.id,
        tool_name=tool_name,
        output_name=output_name,
        output_path=output_path,
    )
    db.session.add(item)
    db.session.commit()


@history_bp.get("/")
@login_required
def list_history():
    entries = (
        FileHistory.query
        .filter_by(user_id=current_user.id)
        .order_by(FileHistory.created_at.desc(), FileHistory.id.desc())
        .all()
    )
    return jsonify([
        {
            "id": entry.id,
            "tool_name": entry.tool_name,
            "output_name": entry.output_name,
            "output_path": entry.output_path,
            "created_at": entry.created_at.isoformat() + "Z",
        }
        for entry in entries
    ])


@history_bp.delete("/<int:entry_id>")
@login_required
def delete_history_entry(entry_id):
    entry = FileHistory.query.filter_by(id=entry_id, user_id=current_user.id).first()
    if not entry:
        return jsonify({"error": "not found"}), 404
    path = Path(entry.output_path)
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except OSError:
        pass
    db.session.delete(entry)
    db.session.commit()
    return jsonify({"ok": True})


@history_bp.delete("/")
@login_required
def clear_history():
    entries = FileHistory.query.filter_by(user_id=current_user.id).all()
    deleted = 0
    for entry in entries:
        path = Path(entry.output_path)
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except OSError:
            pass
        db.session.delete(entry)
        deleted += 1
    db.session.commit()
    return jsonify({"deleted": deleted})
