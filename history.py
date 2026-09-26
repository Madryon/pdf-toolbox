from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from extensions import db
from models import FileHistory

history_bp = Blueprint("history", __name__)


@history_bp.route("/history", methods=["GET"])
@login_required
def get_history():
    rows = (
        FileHistory.query.filter_by(user_id=current_user.id)
        .order_by(FileHistory.created_at.desc())
        .all()
    )
    return jsonify(
        [
            {
                "id": row.id,
                "tool_name": row.tool_name,
                "output_name": row.output_name,
                "output_path": row.output_path,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    )


@history_bp.route("/history/<int:history_id>", methods=["DELETE"])
@login_required
def delete_history_item(history_id):
    row = FileHistory.query.filter_by(id=history_id, user_id=current_user.id).first()
    if not row:
        return jsonify({"error": "history item not found"}), 404
    db.session.delete(row)
    db.session.commit()
    return jsonify({"ok": True})


@history_bp.route("/history/", methods=["DELETE"])
@login_required
def clear_history():
    FileHistory.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})
