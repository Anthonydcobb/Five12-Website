"""Safe import and rollback helpers for vendor fixture catalogs."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from . import db
from .models import Fixture, FixtureLibraryBackup

HOG_SUMMARY_NAMESPACE = "http://schemav5.hogfour.com/Summary"
_HOG = f"{{{HOG_SUMMARY_NAMESPACE}}}"
MAX_SUMMARY_XML_BYTES = 25 * 1024 * 1024
MAX_FIXTURE_RECORDS = 100_000
BACKUP_SCHEMA_VERSION = 1
_ALLOWED_LIBRARY_TYPES = {"type", "part", "compound"}
_SNAPSHOT_FIELDS = (
    "id",
    "fixture",
    "channel_count",
    "wattage",
    "weight",
    "firmware",
    "notes",
    "manufacturer",
    "hog_uuid",
    "revision_id",
    "library_type",
    "library_origin",
    "library_source",
    "library_version",
)
_SQLITE_FIXTURE_COLUMNS = {
    "manufacturer": "VARCHAR(120)",
    "hog_uuid": "VARCHAR(36)",
    "revision_id": "INTEGER",
    "library_type": "VARCHAR(20)",
    "library_origin": "VARCHAR(120)",
    "library_source": "VARCHAR(50)",
    "library_version": "VARCHAR(32)",
}


class FixtureLibraryError(ValueError):
    """Raised when an uploaded fixture catalog is unsafe or unsupported."""


class FixtureLibraryBusyError(RuntimeError):
    """Raised when another process is already replacing the catalog."""


@dataclass(frozen=True)
class ParsedFixtureLibrary:
    records: list[dict]
    source: str
    version: str
    manufacturer_count: int
    fixture_count: int
    patchable_count: int
    part_count: int
    compound_count: int
    genesis: str


def ensure_desktop_fixture_library_schema() -> None:
    """Idempotently upgrade a legacy create_all-based desktop SQLite catalog.

    Older desktop databases do not carry Alembic state. SQLite also cannot
    change a NOT NULL column in place, so legacy fixture tables are rebuilt in
    one transaction. Unknown vendor wattage/weight can then remain NULL rather
    than being fabricated as zero.
    """

    if db.engine.dialect.name != "sqlite":
        return

    inspector = inspect(db.engine)
    if "fixtures" not in inspector.get_table_names():
        return

    columns = {column["name"]: column for column in inspector.get_columns("fixtures")}
    needs_rebuild = (
        any(name not in columns for name in _SQLITE_FIXTURE_COLUMNS)
        or not columns["wattage"]["nullable"]
        or not columns["weight"]["nullable"]
    )

    if needs_rebuild:
        target_columns = [
            "id", "fixture", "channel_count", "wattage", "weight",
            "firmware", "notes", *_SQLITE_FIXTURE_COLUMNS,
        ]
        select_columns = [name if name in columns else "NULL" for name in target_columns]
        with db.engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE fixtures_five12_upgrade (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fixture VARCHAR(120) NOT NULL,
                    channel_count INTEGER NOT NULL,
                    wattage INTEGER,
                    weight INTEGER,
                    firmware VARCHAR(120),
                    notes TEXT,
                    manufacturer VARCHAR(120),
                    hog_uuid VARCHAR(36),
                    revision_id INTEGER,
                    library_type VARCHAR(20),
                    library_origin VARCHAR(120),
                    library_source VARCHAR(50),
                    library_version VARCHAR(32)
                )
            """))
            connection.execute(text(
                f"INSERT INTO fixtures_five12_upgrade ({', '.join(target_columns)}) "
                f"SELECT {', '.join(select_columns)} FROM fixtures"
            ))
            connection.execute(text("DROP TABLE fixtures"))
            connection.execute(text(
                "ALTER TABLE fixtures_five12_upgrade RENAME TO fixtures"
            ))

    FixtureLibraryBackup.__table__.create(bind=db.engine, checkfirst=True)
    for index in Fixture.__table__.indexes:
        index.create(bind=db.engine, checkfirst=True)


@contextmanager
def fixture_catalog_mutation_lock():
    """Serialize destructive catalog operations across app processes.

    MySQL uses a connection-scoped advisory lock. SQLite starts an immediate
    write transaction, so a competing writer receives a clean 409 after the
    connection's normal bounded lock wait instead of taking a stale backup.
    """

    dialect = db.engine.dialect.name
    session_connection = None
    lock_connection = None
    mysql_lock_acquired = False
    try:
        if dialect == "mysql":
            lock_connection = db.engine.connect()
            mysql_lock_acquired = bool(lock_connection.execute(
                text("SELECT GET_LOCK('five12_fixture_catalog', 0)")
            ).scalar())
            if not mysql_lock_acquired:
                raise FixtureLibraryBusyError(
                    "Another fixture-library operation is already running"
                )
        elif dialect == "sqlite":
            session_connection = db.session.connection()
            try:
                session_connection.exec_driver_sql("BEGIN IMMEDIATE")
            except OperationalError as exc:
                raise FixtureLibraryBusyError(
                    "Another fixture-library operation is already running"
                ) from exc
        yield
    finally:
        if dialect == "mysql" and lock_connection is not None:
            if mysql_lock_acquired:
                lock_connection.execute(
                    text("SELECT RELEASE_LOCK('five12_fixture_catalog')")
                )
            lock_connection.close()


def _required_text(value: str | None, label: str, max_length: int) -> str:
    text = (value or "").strip()
    if not text:
        raise FixtureLibraryError(f"Missing {label} in Hog summary.xml")
    if len(text) > max_length:
        raise FixtureLibraryError(
            f"{label} exceeds Five12's {max_length}-character limit"
        )
    return text


def _required_int(value: str | None, label: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value or "")
    except (TypeError, ValueError) as exc:
        raise FixtureLibraryError(f"Invalid {label} in Hog summary.xml") from exc
    if not minimum <= parsed <= maximum:
        raise FixtureLibraryError(
            f"{label} must be between {minimum} and {maximum}"
        )
    return parsed


def parse_hog_summary(xml_bytes: bytes) -> ParsedFixtureLibrary:
    """Validate an official Hog v5 summary.xml and return import mappings.

    ElementTree does not fetch external resources, and DTD/entity declarations
    are rejected before parsing. The byte and record limits bound memory use.
    """

    if not xml_bytes:
        raise FixtureLibraryError("The selected XML file is empty")
    if len(xml_bytes) > MAX_SUMMARY_XML_BYTES:
        raise FixtureLibraryError(
            f"summary.xml is larger than the {MAX_SUMMARY_XML_BYTES // (1024 * 1024)} MB limit"
        )

    lowered = xml_bytes.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise FixtureLibraryError("DTD and entity declarations are not allowed")

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise FixtureLibraryError(f"Malformed XML: {exc}") from exc

    if root.tag != f"{_HOG}library":
        raise FixtureLibraryError(
            "Unsupported XML. Expected a Hog v5 summary.xml library document."
        )

    genesis = (root.findtext(f"{_HOG}genesis") or "").strip()
    version_match = re.search(r"Library\s+version\s*\(v([^\)]+)\)", genesis, re.I)
    if not version_match:
        raise FixtureLibraryError("Hog library version is missing from genesis")
    version = version_match.group(1).strip()
    if not re.fullmatch(r"[0-9A-Za-z._-]{1,32}", version):
        raise FixtureLibraryError("Hog library version has an unsupported format")

    records: list[dict] = []
    manufacturer_count = 0
    type_counts: Counter[str] = Counter()

    for manufacturer_element in root.findall(f"{_HOG}mfr"):
        manufacturer = _required_text(
            manufacturer_element.get("name"), "manufacturer name", 120
        )
        manufacturer_count += 1

        for fixture_element in manufacturer_element.findall(f"{_HOG}fixture"):
            if len(records) >= MAX_FIXTURE_RECORDS:
                raise FixtureLibraryError(
                    f"Fixture count exceeds the {MAX_FIXTURE_RECORDS:,}-record limit"
                )

            fixture_name = _required_text(
                fixture_element.get("name"), "fixture name", 120
            )
            hog_uuid = _required_text(
                fixture_element.get("hoguuid"), "Hog UUID", 36
            ).lower()
            try:
                uuid.UUID(hog_uuid)
            except ValueError as exc:
                raise FixtureLibraryError(
                    f"Invalid Hog UUID for {manufacturer} / {fixture_name}"
                ) from exc

            footprint = _required_int(
                fixture_element.get("dmxfootprint"), "DMX footprint", 1, 4096
            )
            revision_id = _required_int(
                fixture_element.get("revisionid"), "revision ID", 0, 1_000_000
            )
            library_type = _required_text(
                fixture_element.get("type"), "fixture library type", 20
            ).lower()
            if library_type not in _ALLOWED_LIBRARY_TYPES:
                raise FixtureLibraryError(
                    f"Unsupported fixture library type: {library_type}"
                )

            origin = (fixture_element.get("origin") or "").strip() or None
            if origin and len(origin) > 120:
                raise FixtureLibraryError("Fixture-library origin is too long")

            records.append(
                {
                    "fixture": fixture_name,
                    "channel_count": footprint,
                    "wattage": None,
                    "weight": None,
                    "firmware": None,
                    "notes": None,
                    "manufacturer": manufacturer,
                    "hog_uuid": hog_uuid,
                    "revision_id": revision_id,
                    "library_type": library_type,
                    "library_origin": origin,
                    "library_source": "Hog 5",
                    "library_version": version,
                }
            )
            type_counts[library_type] += 1

    if not records:
        raise FixtureLibraryError("No fixture profiles were found in summary.xml")

    patchable_count = sum(
        record["library_type"] != "part" and record["channel_count"] <= 512
        for record in records
    )
    return ParsedFixtureLibrary(
        records=records,
        source="Hog 5",
        version=version,
        manufacturer_count=manufacturer_count,
        fixture_count=len(records),
        patchable_count=patchable_count,
        part_count=type_counts["part"],
        compound_count=type_counts["compound"],
        genesis=genesis,
    )


def snapshot_fixtures(*, for_update: bool = False) -> list[dict]:
    """Return an exact JSON-safe snapshot of the current fixture rows."""

    query = Fixture.query.order_by(Fixture.id)
    if for_update and db.engine.dialect.name == "mysql":
        # The advisory lock serializes library operations; row/gap locks also
        # keep ordinary fixture CRUD from racing the backup/delete transaction.
        query = query.with_for_update()
    return [
        {field: getattr(fixture, field) for field in _SNAPSHOT_FIELDS}
        for fixture in query.all()
    ]


def _catalog_identity(snapshot: list[dict]) -> tuple[str | None, str | None]:
    sources = {row.get("library_source") for row in snapshot if row.get("library_source")}
    versions = {row.get("library_version") for row in snapshot if row.get("library_version")}
    return (
        next(iter(sources)) if len(sources) == 1 else None,
        next(iter(versions)) if len(versions) == 1 else None,
    )


def _snapshot_checksum(snapshot: list[dict]) -> str:
    canonical = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def fixture_catalog_state(*, for_update: bool = False) -> tuple[int, str]:
    """Return row count and stable identity, optionally locking MySQL rows."""

    snapshot = snapshot_fixtures(for_update=for_update)
    return len(snapshot), _snapshot_checksum(snapshot)


def fixture_catalog_checksum(*, for_update: bool = False) -> str:
    """Return a stable identity for every persisted field in the catalog."""

    return fixture_catalog_state(for_update=for_update)[1]


def validate_fixture_backup(backup: FixtureLibraryBackup) -> list[dict]:
    snapshot = backup.fixtures_json
    if backup.schema_version != BACKUP_SCHEMA_VERSION:
        raise FixtureLibraryError(
            f"Fixture backup #{backup.id} uses an unsupported schema version"
        )
    if not isinstance(snapshot, list) or len(snapshot) != backup.fixture_count:
        raise FixtureLibraryError(
            f"Fixture backup #{backup.id} failed its row-count integrity check"
        )
    if _snapshot_checksum(snapshot) != backup.checksum:
        raise FixtureLibraryError(
            f"Fixture backup #{backup.id} failed its checksum integrity check"
        )
    return snapshot


def create_fixture_backup(reason: str) -> FixtureLibraryBackup:
    snapshot = snapshot_fixtures()
    source, version = _catalog_identity(snapshot)
    backup = FixtureLibraryBackup(
        reason=reason[:200],
        fixture_count=len(snapshot),
        source=source,
        version=version,
        schema_version=BACKUP_SCHEMA_VERSION,
        checksum=_snapshot_checksum(snapshot),
        fixtures_json=snapshot,
    )
    db.session.add(backup)
    db.session.flush()
    return backup


def replace_with_hog_library(parsed: ParsedFixtureLibrary) -> FixtureLibraryBackup:
    """Back up current fixtures and replace them in the caller's transaction."""

    backup = create_fixture_backup(
        f"Before importing Hog 5 fixture library {parsed.version}"
    )
    Fixture.query.delete(synchronize_session=False)
    db.session.bulk_insert_mappings(Fixture, parsed.records)
    return backup


def restore_fixture_backup(backup: FixtureLibraryBackup) -> FixtureLibraryBackup:
    """Back up the current catalog, then restore the selected snapshot."""

    snapshot = validate_fixture_backup(backup)
    rollback_backup = create_fixture_backup(
        f"Before restoring fixture backup #{backup.id}"
    )
    Fixture.query.delete(synchronize_session=False)
    db.session.bulk_insert_mappings(Fixture, snapshot)
    return rollback_backup
