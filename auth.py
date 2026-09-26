from flask import Blueprint, jsonify, request
from flask_login import login_required, login_user, logout_user

from extensions import db, login_manager
from models import User

auth_bp = Blueprint("auth", __name__)


def _field(name):
    return (request.form.get(name) or (request.get_json(silent=True) or {}).get(name) or "").strip()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@auth_bp.route("/register", methods=["POST"])
def register():
    email = _field("email").lower()
    password = _field("password")
    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "email already registered"}), 409
    user = User(email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    login_user(user)
    return jsonify({"ok": True, "user_id": user.id}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    email = _field("email").lower()
    password = _field("password")
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "invalid credentials"}), 401
    login_user(user)
    return jsonify({"ok": True})


@auth_bp.route("/logout", methods=["POST", "GET"])
@login_required
def logout():
    logout_user()
    return jsonify({"ok": True})
