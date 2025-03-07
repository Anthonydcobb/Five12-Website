from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from app import db


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(255), nullable=False)
    username = db.Column(db.String(255), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_approved = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)


class Show(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    
    # ✅ Correct relationship, ensure Patch references show_id
    patches = db.relationship("Patch", back_populates="show", cascade="all, delete-orphan")


class Patch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    show_id = db.Column(db.Integer, db.ForeignKey("show.id", ondelete="CASCADE"), nullable=False)

    # ✅ Add relationship to PatchFixture
    fixtures = db.relationship("PatchFixture", back_populates="patch", cascade="all, delete-orphan")

    show = db.relationship("Show", back_populates="patches")


class Fixture(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    manufacturer = db.Column(db.String(255), nullable=False)
    fixture_type = db.Column(db.String(255), nullable=False)
    mode = db.Column(db.String(255), nullable=False)
    channel_count = db.Column(db.Integer, nullable=False)
    wattage = db.Column(db.Integer, nullable=True)
    weight = db.Column(db.Float, nullable=True)
    firmware = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # ✅ Add relationship to PatchFixture
    patches = db.relationship("PatchFixture", back_populates="fixture", cascade="all, delete-orphan")

class PatchFixture(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patch_id = db.Column(db.Integer, db.ForeignKey("patch.id", ondelete="CASCADE"), nullable=False)
    fixture_id = db.Column(db.Integer, db.ForeignKey("fixture.id", ondelete="CASCADE"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    notes = db.Column(db.Text, nullable=True)  # ✅ New Notes Column

    # Relationships
    patch = db.relationship("Patch", back_populates="fixtures")
    fixture = db.relationship("Fixture", back_populates="patches")
