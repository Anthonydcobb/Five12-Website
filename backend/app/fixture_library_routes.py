"""Fixture-library import, backup, download, and restore API."""

import json
import hashlib
import re
from io import BytesIO
from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify, request, send_file
from sqlalchemy import or_
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import db
from .fixture_library import (
    MAX_SUMMARY_XML_BYTES,
    FixtureLibraryBusyError,
    FixtureLibraryError,
    fixture_catalog_checksum,
    fixture_catalog_state,
    fixture_catalog_mutation_lock,
    parse_hog_summary,
    replace_with_hog_library,
    restore_fixture_backup,
    validate_fixture_backup,
)
from .models import Fixture, FixtureLibraryBackup

fixture_library = Blueprint("fixture_library", __name__)


def _confirmed(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _reject_foreign_origin():
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.host:
        return jsonify({"error": "Cross-origin catalog mutations are not allowed"}), 403
    return None


def _preview_serializer():
    return URLSafeTimedSerializer(
        current_app.secret_key, salt="five12-hog-fixture-import"
    )


def _bounded_query_args():
    query = request.args.get("q", "").strip()
    if len(query) > 120:
        raise FixtureLibraryError("Search query is too long")
    try:
        limit = min(max(int(request.args.get("limit", 200)), 1), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError as exc:
        raise FixtureLibraryError("Invalid fixture search range") from exc
    return query, limit, offset


def _filtered_fixture_query(patchable=False, tokenized=False):
    query_text, limit, offset = _bounded_query_args()
    query = Fixture.query
    if patchable:
        query = query.filter(Fixture.channel_count.between(1, 512)).filter(
            or_(Fixture.library_type.is_(None), Fixture.library_type != "part")
        )
    if query_text:
        search_terms = (
            re.findall(r"[a-z0-9]+", query_text.lower())
            if tokenized else [query_text]
        )
        if tokenized and not search_terms:
            query = query.filter(Fixture.id.is_(None))
        for term in search_terms:
            escaped = (
                term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            query = query.filter(or_(
                Fixture.fixture.ilike(pattern, escape="\\"),
                Fixture.manufacturer.ilike(pattern, escape="\\"),
            ))
        if tokenized:
            for index, term in enumerate(search_terms[:-1]):
                if term in {"mode", "personality"}:
                    mode_pattern = f"%{term}%{search_terms[index + 1]}%"
                    query = query.filter(Fixture.fixture.ilike(mode_pattern))
    total = query.count()
    fixtures = query.order_by(
        Fixture.manufacturer, Fixture.fixture, Fixture.id
    ).offset(offset).limit(limit).all()
    return fixtures, total, limit, offset


def _read_hog_upload():
    if "file" not in request.files:
        raise FixtureLibraryError("Select the Hog summary.xml file")
    xml_bytes = request.files["file"].stream.read(MAX_SUMMARY_XML_BYTES + 1)
    return xml_bytes, parse_hog_summary(xml_bytes)


@fixture_library.get("/api/fixture-library/patch-profiles")
def list_patchable_fixture_profiles():
    """Search patchable profiles without sending the whole Hog catalog."""

    try:
        fixtures, total, limit, offset = _filtered_fixture_query(
            patchable=True, tokenized=True
        )
    except FixtureLibraryError as exc:
        return jsonify({"error": str(exc)}), 400
    items = [
        {
            "id": fixture.id,
            "fixture": fixture.fixture,
            "displayName": (
                f"{fixture.manufacturer} — {fixture.fixture}"
                if fixture.manufacturer else fixture.fixture
            ),
            "channelCount": fixture.channel_count,
            "wattage": fixture.wattage,
            "weight": fixture.weight,
            "firmware": fixture.firmware,
            "notes": fixture.notes,
            "manufacturer": fixture.manufacturer,
            "libraryType": fixture.library_type,
            "selectionToken": fixture.selection_token(),
            "isPatchable": True,
            "unsupportedReason": None,
        }
        for fixture in fixtures
    ]
    return jsonify({"items": items, "total": total, "limit": limit, "offset": offset})


@fixture_library.get("/api/fixture-library/catalog")
def search_fixture_catalog():
    """Paginated catalog search for the database-management page."""

    try:
        fixtures, total, limit, offset = _filtered_fixture_query()
    except FixtureLibraryError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "items": [fixture.to_dict() for fixture in fixtures],
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@fixture_library.get("/api/fixture-library/status")
def fixture_library_status():
    total = Fixture.query.count()
    first_library_fixture = (
        Fixture.query.filter(Fixture.library_source.isnot(None))
        .order_by(Fixture.id)
        .first()
    )
    return jsonify(
        {
            "fixtureCount": total,
            "catalogChecksum": fixture_catalog_checksum(),
            "source": (
                first_library_fixture.library_source if first_library_fixture else None
            ),
            "version": (
                first_library_fixture.library_version if first_library_fixture else None
            ),
        }
    )


@fixture_library.get("/api/fixture-library/backups")
def list_fixture_library_backups():
    backups = FixtureLibraryBackup.query.order_by(
        FixtureLibraryBackup.created_at.desc(), FixtureLibraryBackup.id.desc()
    ).all()
    return jsonify([backup.to_dict() for backup in backups])


@fixture_library.get("/api/fixture-library/backups/<int:backup_id>/download")
def download_fixture_library_backup(backup_id):
    backup = FixtureLibraryBackup.query.get_or_404(backup_id)
    try:
        snapshot = validate_fixture_backup(backup)
    except FixtureLibraryError as exc:
        return jsonify({"error": str(exc)}), 409
    payload = {
        "format": "five12-fixture-backup-v1",
        "backup": backup.to_dict(),
        "fixtures": snapshot,
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return send_file(
        BytesIO(data),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"five12-fixtures-backup-{backup.id}.json",
    )


@fixture_library.post("/api/fixture-library/hog/preview")
def preview_hog_fixture_library():
    if rejection := _reject_foreign_origin():
        return rejection
    try:
        xml_bytes, parsed = _read_hog_upload()
    except FixtureLibraryError as exc:
        return jsonify({"error": str(exc)}), 400

    current_count = Fixture.query.count()
    preview_payload = {
        "digest": hashlib.sha256(xml_bytes).hexdigest(),
        "source": parsed.source,
        "version": parsed.version,
        "fixtureCount": parsed.fixture_count,
        "currentCount": current_count,
        "currentCatalogChecksum": fixture_catalog_checksum(),
    }
    token = _preview_serializer().dumps(preview_payload)
    return jsonify({
        **preview_payload,
        "manufacturers": parsed.manufacturer_count,
        "patchable": parsed.patchable_count,
        "parts": parsed.part_count,
        "compounds": parsed.compound_count,
        "unsupported": parsed.fixture_count - parsed.patchable_count,
        "previewToken": token,
    })


@fixture_library.post("/api/fixture-library/hog/import")
def import_hog_fixture_library():
    if rejection := _reject_foreign_origin():
        return rejection
    if not _confirmed(request.form.get("confirmReplace")):
        return jsonify(
            {
                "error": (
                    "Replacement confirmation is required. The current fixture "
                    "catalog will be backed up before it is replaced."
                )
            }
        ), 400
    try:
        xml_bytes, parsed = _read_hog_upload()
        preview = _preview_serializer().loads(
            request.form.get("previewToken", ""), max_age=15 * 60
        )
        expected_file = {
            "digest": hashlib.sha256(xml_bytes).hexdigest(),
            "source": parsed.source,
            "version": parsed.version,
            "fixtureCount": parsed.fixture_count,
        }
        if any(preview.get(key) != value for key, value in expected_file.items()):
            raise FixtureLibraryError(
                "The file changed after preview; preview it again"
            )
    except SignatureExpired:
        return jsonify({"error": "The import preview expired; preview it again"}), 400
    except BadSignature:
        return jsonify({"error": "A valid import preview is required"}), 400
    except FixtureLibraryError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        with fixture_catalog_mutation_lock():
            current_count, current_checksum = fixture_catalog_state(for_update=True)
            if (
                preview.get("currentCount") != current_count
                or preview.get("currentCatalogChecksum") != current_checksum
            ):
                raise FixtureLibraryError(
                    "The current catalog changed after preview; preview it again"
                )
            backup = replace_with_hog_library(parsed)
            db.session.commit()
    except FixtureLibraryBusyError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 409
    except FixtureLibraryError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Hog fixture-library replacement failed")
        return jsonify(
            {
                "error": (
                    "The fixture import failed. No fixture changes were committed."
                )
            }
        ), 500

    return jsonify(
        {
            "imported": parsed.fixture_count,
            "manufacturers": parsed.manufacturer_count,
            "patchable": parsed.patchable_count,
            "parts": parsed.part_count,
            "compounds": parsed.compound_count,
            "source": parsed.source,
            "version": parsed.version,
            "backup": backup.to_dict(),
            "backupDownloadUrl": (
                f"/api/fixture-library/backups/{backup.id}/download"
            ),
        }
    ), 201


@fixture_library.post("/api/fixture-library/backups/<int:backup_id>/restore")
def restore_fixture_library_backup(backup_id):
    if rejection := _reject_foreign_origin():
        return rejection
    body = request.get_json(silent=True) or {}
    if not _confirmed(body.get("confirmReplace")):
        return jsonify(
            {
                "error": (
                    "Restore confirmation is required. The current fixture catalog "
                    "will be backed up before it is replaced."
                )
            }
        ), 400

    backup = FixtureLibraryBackup.query.get_or_404(backup_id)
    restored_count = backup.fixture_count
    expected_catalog_checksum = body.get("expectedCatalogChecksum")
    if not expected_catalog_checksum:
        return jsonify({"error": "Current catalog identity is required for restore"}), 400
    try:
        with fixture_catalog_mutation_lock():
            if fixture_catalog_checksum(for_update=True) != expected_catalog_checksum:
                raise FixtureLibraryError(
                    "The current catalog changed before restore; reload and review it again"
                )
            rollback_backup = restore_fixture_backup(backup)
            db.session.commit()
    except FixtureLibraryBusyError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 409
    except FixtureLibraryError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Fixture-library backup restore failed for backup %s", backup_id
        )
        return jsonify(
            {
                "error": (
                    "The fixture restore failed. No fixture changes were committed."
                )
            }
        ), 500

    return jsonify(
        {
            "restored": restored_count,
            "fromBackup": backup.to_dict(),
            "rollbackBackup": rollback_backup.to_dict(),
            "rollbackBackupDownloadUrl": (
                f"/api/fixture-library/backups/{rollback_backup.id}/download"
            ),
        }
    )
