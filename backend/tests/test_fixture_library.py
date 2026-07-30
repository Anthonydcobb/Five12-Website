import io
import json
import sqlite3
import threading
from pathlib import Path

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from app import create_app, db as app_db
from app.fixture_library import (
    MAX_SUMMARY_XML_BYTES,
    FixtureLibraryBusyError,
    FixtureLibraryError,
    fixture_catalog_mutation_lock,
    parse_hog_summary,
)
from app.sqlite_schema import upgrade_sqlite_schema
from app.models import Fixture, FixtureLibraryBackup, PatchSheet, Show


NS = "http://schemav5.hogfour.com/Summary"


def hog_xml(fixtures=None, namespace=NS, genesis="Created For Library version (v5.0.766)"):
    fixtures = fixtures or [
        {
            "manufacturer": "Test Light",
            "name": "Pixel Bar Mode 1",
            "uuid": "11111111-1111-4111-8111-111111111111",
            "footprint": 16,
            "revision": 2,
            "type": "type",
            "origin": "High End Systems",
        },
        {
            "manufacturer": "Test Light",
            "name": "Pixel Bar Cell",
            "uuid": "22222222-2222-4222-8222-222222222222",
            "footprint": 4,
            "revision": 1,
            "type": "part",
            "origin": "Carallon",
        },
        {
            "manufacturer": "Other Co",
            "name": "Huge Compound",
            "uuid": "33333333-3333-4333-8333-333333333333",
            "footprint": 600,
            "revision": 0,
            "type": "compound",
            "origin": "High End Systems",
        },
    ]
    by_manufacturer = {}
    for fixture in fixtures:
        by_manufacturer.setdefault(fixture["manufacturer"], []).append(fixture)
    body = []
    for manufacturer, profiles in by_manufacturer.items():
        body.append(f'<mfr name="{manufacturer}">')
        for profile in profiles:
            body.append(
                '<fixture '
                f'name="{profile["name"]}" '
                f'hoguuid="{profile["uuid"]}" '
                f'dmxfootprint="{profile["footprint"]}" '
                f'origin="{profile["origin"]}" '
                f'revisionid="{profile["revision"]}" '
                f'type="{profile["type"]}" />'
            )
        body.append("</mfr>")
    return (
        '<?xml version="1.0"?>'
        f'<library xmlns="{namespace}"><genesis>{genesis}</genesis>'
        + "".join(body)
        + "</library>"
    ).encode()


@pytest.fixture(autouse=True)
def clean_fixture_catalog(app):
    with app.app_context():
        Fixture.query.delete()
        FixtureLibraryBackup.query.delete()
        app_db.session.commit()
    yield
    with app.app_context():
        app_db.session.rollback()
        Fixture.query.delete()
        FixtureLibraryBackup.query.delete()
        app_db.session.commit()


def add_legacy_fixture(app):
    with app.app_context():
        fixture = Fixture(
            fixture="Legacy Fixture",
            channel_count=7,
            wattage=125,
            weight=9,
            firmware="1.2.3",
            notes="Keep me safe",
        )
        app_db.session.add(fixture)
        app_db.session.commit()
        return fixture.id


def upload(client, xml, confirm=True):
    preview = client.post(
        "/api/fixture-library/hog/preview",
        data={"file": (io.BytesIO(xml), "summary.xml")},
        content_type="multipart/form-data",
    )
    if preview.status_code != 200:
        return preview
    data = {
        "file": (io.BytesIO(xml), "summary.xml"),
        "previewToken": preview.get_json()["previewToken"],
    }
    if confirm:
        data["confirmReplace"] = "true"
    return client.post(
        "/api/fixture-library/hog/import",
        data=data,
        content_type="multipart/form-data",
    )


def restore(client, backup_id, checksum=None):
    checksum = checksum or client.get(
        "/api/fixture-library/status"
    ).get_json()["catalogChecksum"]
    return client.post(
        f"/api/fixture-library/backups/{backup_id}/restore",
        json={
            "confirmReplace": True,
            "expectedCatalogChecksum": checksum,
        },
    )


@pytest.mark.parametrize(
    "message",
    ["database is locked", "database table is locked", "database schema is locked"],
)
def test_sqlite_lock_contention_is_reported_as_fixture_library_busy(app, monkeypatch, message):
    failure = OperationalError(
        "BEGIN IMMEDIATE", {}, sqlite3.OperationalError(message)
    )

    class FailingConnection:
        def exec_driver_sql(self, _statement):
            raise failure

    with app.app_context():
        monkeypatch.setattr(app_db.session, "connection", lambda: FailingConnection())
        with pytest.raises(FixtureLibraryBusyError, match="already running"):
            with fixture_catalog_mutation_lock():
                pass


def test_unrelated_sqlite_operational_error_is_not_mislabeled_as_busy(app, monkeypatch):
    failure = OperationalError(
        "BEGIN IMMEDIATE",
        {},
        sqlite3.OperationalError("cannot start a transaction within a transaction"),
    )

    class FailingConnection:
        def exec_driver_sql(self, _statement):
            raise failure

    with app.app_context():
        monkeypatch.setattr(app_db.session, "connection", lambda: FailingConnection())
        with pytest.raises(OperationalError, match="cannot start a transaction"):
            with fixture_catalog_mutation_lock():
                pass


def test_parser_preserves_official_summary_fields_and_marks_patchable_profiles():
    parsed = parse_hog_summary(hog_xml())

    assert parsed.source == "Hog 5"
    assert parsed.version == "5.0.766"
    assert parsed.manufacturer_count == 2
    assert parsed.fixture_count == 3
    assert parsed.patchable_count == 1
    assert parsed.part_count == 1
    assert parsed.compound_count == 1
    assert parsed.records[0] == {
        "fixture": "Pixel Bar Mode 1",
        "channel_count": 16,
        "wattage": None,
        "weight": None,
        "firmware": None,
        "notes": None,
        "manufacturer": "Test Light",
        "hog_uuid": "11111111-1111-4111-8111-111111111111",
        "revision_id": 2,
        "library_type": "type",
        "library_origin": "High End Systems",
        "library_source": "Hog 5",
        "library_version": "5.0.766",
    }


@pytest.mark.parametrize(
    "payload, error_text",
    [
        (b"<not-xml", "Malformed XML"),
        (b'<!DOCTYPE x [<!ENTITY y "z">]><x>&y;</x>', "DTD and entity"),
        (hog_xml(namespace="urn:not-hog"), "Expected a Hog v5 summary.xml"),
        (hog_xml(genesis="no version here"), "version is missing"),
    ],
)
def test_parser_rejects_unsafe_or_unsupported_xml(payload, error_text):
    with pytest.raises(FixtureLibraryError, match=error_text):
        parse_hog_summary(payload)


def test_parser_rejects_oversized_upload():
    with pytest.raises(FixtureLibraryError, match="larger than"):
        parse_hog_summary(b"x" * (MAX_SUMMARY_XML_BYTES + 1))


def test_import_requires_explicit_replacement_confirmation(client, app):
    legacy_id = add_legacy_fixture(app)

    response = upload(client, hog_xml(), confirm=False)

    assert response.status_code == 400
    with app.app_context():
        assert Fixture.query.one().id == legacy_id
        assert FixtureLibraryBackup.query.count() == 0


def test_import_backs_up_then_atomically_replaces_fixture_catalog(client, app):
    legacy_id = add_legacy_fixture(app)

    response = upload(client, hog_xml())

    assert response.status_code == 201
    result = response.get_json()
    assert result["imported"] == 3
    assert result["manufacturers"] == 2
    assert result["patchable"] == 1
    assert result["version"] == "5.0.766"
    assert result["backup"]["fixtureCount"] == 1

    profiles = client.get("/api/fixture-library/patch-profiles")
    assert profiles.status_code == 200
    assert [profile["displayName"] for profile in profiles.get_json()["items"]] == [
        "Test Light — Pixel Bar Mode 1"
    ]

    with app.app_context():
        assert Fixture.query.count() == 3
        imported = Fixture.query.filter_by(hog_uuid="11111111-1111-4111-8111-111111111111").one()
        assert imported.manufacturer == "Test Light"
        assert imported.channel_count == 16
        assert imported.wattage is None
        assert imported.weight is None
        assert imported.firmware is None
        backup = FixtureLibraryBackup.query.one()
        assert backup.schema_version == 1
        assert len(backup.checksum) == 64
        assert backup.fixtures_json[0]["id"] == legacy_id
        assert backup.fixtures_json[0]["notes"] == "Keep me safe"


def test_invalid_xml_does_not_create_backup_or_change_fixtures(client, app):
    legacy_id = add_legacy_fixture(app)

    response = upload(client, b"<broken")

    assert response.status_code == 400
    with app.app_context():
        assert Fixture.query.one().id == legacy_id
        assert FixtureLibraryBackup.query.count() == 0


def test_database_failure_rolls_back_backup_delete_and_insert(client, app, monkeypatch):
    legacy_id = add_legacy_fixture(app)

    def fail_bulk_insert(*_args, **_kwargs):
        raise RuntimeError("simulated insert failure")

    monkeypatch.setattr(app_db.session, "bulk_insert_mappings", fail_bulk_insert)
    response = upload(client, hog_xml())

    assert response.status_code == 500
    assert response.get_json()["error"] == (
        "The fixture import failed. No fixture changes were committed."
    )
    with app.app_context():
        assert Fixture.query.one().id == legacy_id
        assert FixtureLibraryBackup.query.count() == 0


def test_backup_can_be_downloaded_and_restored_with_rollback_backup(client, app):
    legacy_id = add_legacy_fixture(app)
    imported = upload(client, hog_xml()).get_json()
    backup_id = imported["backup"]["id"]

    download = client.get(f"/api/fixture-library/backups/{backup_id}/download")
    assert download.status_code == 200
    assert download.headers["Content-Disposition"].startswith("attachment;")
    downloaded = json.loads(download.data)
    assert downloaded["format"] == "five12-fixture-backup-v1"
    assert downloaded["fixtures"][0]["id"] == legacy_id

    response = restore(client, backup_id)
    assert response.status_code == 200
    result = response.get_json()
    assert result["restored"] == 1
    assert result["rollbackBackup"]["fixtureCount"] == 3

    with app.app_context():
        restored = Fixture.query.one()
        assert restored.id == legacy_id
        assert restored.fixture == "Legacy Fixture"
        assert FixtureLibraryBackup.query.count() == 2


def test_restore_requires_confirmation(client, app):
    add_legacy_fixture(app)
    backup_id = upload(client, hog_xml()).get_json()["backup"]["id"]

    response = client.post(
        f"/api/fixture-library/backups/{backup_id}/restore", json={}
    )

    assert response.status_code == 400
    with app.app_context():
        assert Fixture.query.count() == 3
        assert FixtureLibraryBackup.query.count() == 1


def test_import_requires_matching_preview_and_rejects_foreign_origin(client, app):
    add_legacy_fixture(app)
    foreign = client.post(
        "/api/fixture-library/hog/preview",
        headers={"Origin": "https://example.invalid"},
        data={"file": (io.BytesIO(hog_xml()), "summary.xml")},
        content_type="multipart/form-data",
    )
    assert foreign.status_code == 403

    no_preview = client.post(
        "/api/fixture-library/hog/import",
        data={
            "file": (io.BytesIO(hog_xml()), "summary.xml"),
            "confirmReplace": "true",
        },
        content_type="multipart/form-data",
    )
    assert no_preview.status_code == 400
    assert "preview" in no_preview.get_json()["error"].lower()


def test_preview_is_invalidated_if_current_catalog_changes(client, app):
    add_legacy_fixture(app)
    preview = client.post(
        "/api/fixture-library/hog/preview",
        data={"file": (io.BytesIO(hog_xml()), "summary.xml")},
        content_type="multipart/form-data",
    ).get_json()
    with app.app_context():
        fixture = Fixture.query.one()
        fixture.notes = "changed without changing row count"
        app_db.session.commit()
    response = client.post(
        "/api/fixture-library/hog/import",
        data={
            "file": (io.BytesIO(hog_xml()), "summary.xml"),
            "confirmReplace": "true",
            "previewToken": preview["previewToken"],
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 409
    assert "changed after preview" in response.get_json()["error"]
    with app.app_context():
        assert Fixture.query.count() == 1
        assert FixtureLibraryBackup.query.count() == 0


def test_corrupt_backup_is_rejected_before_restore_mutation(client, app):
    add_legacy_fixture(app)
    backup_id = upload(client, hog_xml()).get_json()["backup"]["id"]
    with app.app_context():
        backup = app_db.session.get(FixtureLibraryBackup, backup_id)
        backup.checksum = "0" * 64
        app_db.session.commit()

    response = restore(client, backup_id)
    assert response.status_code == 409
    assert "checksum" in response.get_json()["error"]
    with app.app_context():
        assert Fixture.query.count() == 3
        assert FixtureLibraryBackup.query.count() == 1


def test_restore_rejects_a_catalog_changed_after_operator_review(client, app):
    add_legacy_fixture(app)
    backup_id = upload(client, hog_xml()).get_json()["backup"]["id"]
    reviewed_checksum = client.get(
        "/api/fixture-library/status"
    ).get_json()["catalogChecksum"]
    with app.app_context():
        current = Fixture.query.order_by(Fixture.id).first()
        current.notes = "another operator changed this"
        app_db.session.commit()

    response = restore(client, backup_id, checksum=reviewed_checksum)
    assert response.status_code == 409
    assert "changed before restore" in response.get_json()["error"]
    with app.app_context():
        assert Fixture.query.count() == 3
        assert FixtureLibraryBackup.query.count() == 1


def test_fixture_search_is_bounded_and_patch_picker_excludes_unsupported(client, app):
    upload(client, hog_xml())
    catalog = client.get("/api/fixture-library/catalog?q=Pixel&limit=1").get_json()
    assert catalog["total"] == 2
    assert len(catalog["items"]) == 1
    patchable = client.get(
        "/api/fixture-library/patch-profiles?q=Pixel&limit=200"
    ).get_json()
    assert patchable["total"] == 1
    assert patchable["items"][0]["isPatchable"] is True


def test_patch_row_api_rejects_addresses_outside_one_universe(client, app):
    with app.app_context():
        show = Show(name="Bounds")
        app_db.session.add(show)
        app_db.session.flush()
        sheet = PatchSheet(name="Main", show_id=show.id)
        app_db.session.add(sheet)
        app_db.session.commit()
        sheet_id = sheet.id

    response = client.post(
        f"/api/patch-sheets/{sheet_id}/rows",
        json={
            "fixture": "101", "type": "Too Wide", "channelCount": 20,
            "universe": 1, "address": 500, "endAddress": 519,
        },
    )
    assert response.status_code == 400
    assert "between 1 and 512" in response.get_json()["error"]


def test_sqlite_catalog_lock_rejects_a_concurrent_writer(tmp_path):
    database = tmp_path / "lock-five12.db"
    lock_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-lock",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database}",
        "ENABLE_NETWORK_TOOLS": False,
        "ENABLE_BLE_TOOLS": False,
    })
    with lock_app.app_context():
        app_db.create_all()

    acquired = threading.Event()
    release = threading.Event()

    def hold_lock():
        with lock_app.app_context():
            try:
                with fixture_catalog_mutation_lock():
                    acquired.set()
                    release.wait(timeout=10)
            finally:
                app_db.session.rollback()

    thread = threading.Thread(target=hold_lock)
    thread.start()
    assert acquired.wait(timeout=5)
    try:
        client = lock_app.test_client()
        create_response = client.post("/api/fixtures", json={
            "fixture": "Concurrent edit", "channelCount": 1,
            "wattage": 0, "weight": 0,
        })
        assert create_response.status_code == 409
        assert "already running" in create_response.get_json()["error"]
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_legacy_desktop_sqlite_schema_is_upgraded_idempotently(tmp_path):
    database = tmp_path / "legacy-five12.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE fixtures (
                id INTEGER PRIMARY KEY,
                fixture VARCHAR(120) NOT NULL,
                mode VARCHAR(120),
                channel_count INTEGER NOT NULL,
                wattage INTEGER NOT NULL,
                weight INTEGER NOT NULL,
                firmware VARCHAR(120),
                notes TEXT
            );
            INSERT INTO fixtures
                (fixture, mode, channel_count, wattage, weight, firmware, notes)
            VALUES ('Legacy Fixture', 'Legacy Mode', 7, 125, 9, '1.2.3', 'keep');
            """
        )

    legacy_app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database}",
            "ENABLE_NETWORK_TOOLS": False,
            "ENABLE_BLE_TOOLS": False,
        }
    )
    with legacy_app.app_context():
        # The real desktop startup sequence: create_all() makes the missing
        # tables, then the bridge reconciles the ones that already existed.
        # Run twice to pin idempotency.
        app_db.create_all()
        upgrade_sqlite_schema(app_db.engine, app_db.metadata)
        upgrade_sqlite_schema(app_db.engine, app_db.metadata)

        columns = {
            row[1]
            for row in app_db.session.execute(
                text("PRAGMA table_info(fixtures)")
            )
        }
        assert {
            "manufacturer",
            "hog_uuid",
            "revision_id",
            "library_type",
            "library_origin",
            "library_source",
            "library_version",
        }.issubset(columns)
        nullable = {
            row[1]: row[3] == 0
            for row in app_db.session.execute(text("PRAGMA table_info(fixtures)"))
        }
        assert nullable["wattage"] is True
        assert nullable["weight"] is True
        assert inspect(app_db.engine).has_table("fixture_library_backups")
        assert Fixture.query.one().fixture == "Legacy Fixture"


def test_alembic_downgrade_handles_unknown_hog_power_fields(tmp_path):
    database_path = tmp_path / "migration.sqlite"
    migration_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "migration-test",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        "ENABLE_NETWORK_TOOLS": False,
        "ENABLE_BLE_TOOLS": False,
    })
    migrations = str(Path(__file__).parents[1] / "migrations")

    with migration_app.app_context():
        upgrade(directory=migrations)
        app_db.session.execute(text(
            "INSERT INTO fixtures "
            "(fixture, channel_count, wattage, weight, manufacturer, hog_uuid, "
            "revision_id, library_type, library_origin, library_source, library_version) "
            "VALUES ('Imported Hog', 1, NULL, NULL, 'Hog', "
            "'00000000-0000-0000-0000-000000000001', '1', 'type', 'base', 'Hog 5', '5.0.766')"
        ))
        app_db.session.commit()

        downgrade(revision="c5f1a2b3d4e6", directory=migrations)

        columns = {
            column["name"]: column
            for column in inspect(app_db.engine).get_columns("fixtures")
        }
        row = app_db.session.execute(text(
            "SELECT wattage, weight FROM fixtures WHERE fixture = 'Imported Hog'"
        )).one()
        assert columns["wattage"]["nullable"] is False
        assert columns["weight"]["nullable"] is False
        assert row == (0, 0)
