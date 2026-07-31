import io, json
import pytest
from app import db
from app.models import Show, PatchSheet, PatchRow, Fixture
from app.patch_import import fixture_source_key

def test_analyze_returns_mapping_and_preview(client):
    csv = b"Fixture Type,DMX Addr,Ch,Dimmer\nPAR64,101,8,full\nMac,110,16,\n"
    data = {"file": (io.BytesIO(csv), "foreign.csv")}
    resp = client.post("/api/patch-sheets/1/import/analyze",
                       data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["headerRowIndex"] == 0
    assert body["theirColumns"] == ["Fixture Type", "DMX Addr", "Ch", "Dimmer"]
    assert body["suggestedMapping"] == {"Fixture Type": "type",
        "DMX Addr": "address", "Ch": "channelCount", "Dimmer": None}
    assert body["rowCount"] == 2
    assert body["previewRows"][0]["Fixture Type"] == "PAR64"


def test_match_preview_rejects_fractional_channel_count(client, db):
    pid = _make_patch(db, show_name="T-fractional-count")
    csv = b"Fixture Type,DMX Addr,Ch\nUnsafe Profile,1,12.5\n"
    resp = client.post(
        f"/api/patch-sheets/{pid}/import/matches",
        data=_import_data(csv, {
            "Fixture Type": "type", "DMX Addr": "address", "Ch": "channelCount",
        }),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "whole number" in resp.get_json()["error"]


def _make_patch(db, show_name="T"):
    show = Show(name=show_name)
    db.session.add(show); db.session.commit()
    sheet = PatchSheet(name="U", show_id=show.id)
    db.session.add(sheet); db.session.commit()
    return sheet.id

def _import_data(csv, mapping, selections=None):
    data = {
        "file": (io.BytesIO(csv), "foreign.csv"),
        "mapping": json.dumps(mapping),
        "headerRowIndex": "0",
    }
    if selections is not None:
        data["fixtureSelections"] = json.dumps(selections)
    return data


def _fixture(db, name, count, manufacturer=None):
    fixture = Fixture(
        fixture=name,
        channel_count=count,
        manufacturer=manufacturer,
        library_type="type",
        library_source="Hog 5",
        library_version="5.0.766",
    )
    db.session.add(fixture)
    db.session.commit()
    return fixture


def test_match_preview_groups_rows_and_preselects_only_exact_match(client, db):
    pid = _make_patch(db, show_name="T-match-preview")
    exact = _fixture(db, "SkyPanel S60-C Mode 6", 20, "ARRI")
    fuzzy = _fixture(db, "SkyPanel S60-C Mode 8", 20, "ARRI")
    _fixture(db, "SkyPanel S60-C Mode 6", 18, "ARRI")
    csv = (
        b"Fixture Type,DMX Addr,Ch\n"
        b"ARRI SkyPanel S60-C Mode 6,1,20\n"
        b"arri skypanel s60 c mode 6,21,20\n"
        b"Mystery Panel,100,12\n"
    )
    mapping = {"Fixture Type": "type", "DMX Addr": "address", "Ch": "channelCount"}
    resp = client.post(
        f"/api/patch-sheets/{pid}/import/matches",
        data=_import_data(csv, mapping),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    groups = resp.get_json()["groups"]
    assert len(groups) == 2
    sky = groups[0]
    assert sky["rowCount"] == 2
    assert sky["selectedFixtureId"] == exact.id
    assert [item["id"] for item in sky["suggestions"]] == [exact.id, fuzzy.id]
    mystery = groups[1]
    assert mystery["selectedFixtureId"] is None
    assert all(item["channelCount"] == 12 for item in mystery["suggestions"])
    assert all(item["exact"] is False for item in mystery["suggestions"])


def test_commit_rejects_incompatible_selected_footprint_before_writing(client, db):
    pid = _make_patch(db, show_name="T-bad-selection")
    wrong = _fixture(db, "SkyPanel S60-C Mode 6", 18, "ARRI")
    csv = b"Fixture Type,DMX Addr,Ch\nARRI S60 Mode 6,1,20\n"
    mapping = {"Fixture Type": "type", "DMX Addr": "address", "Ch": "channelCount"}
    key = fixture_source_key("ARRI S60 Mode 6", 20)
    resp = client.post(
        f"/api/patch-sheets/{pid}/import/commit",
        data=_import_data(csv, mapping, {key: wrong.id}),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "20" in resp.get_json()["error"] and "18" in resp.get_json()["error"]
    assert PatchRow.query.filter_by(patch_id=pid).count() == 0


def test_commit_applies_compatible_selection_and_recomputes_end_address(client, db):
    pid = _make_patch(db, show_name="T-good-selection")
    selected = _fixture(db, "Vortex8 Mode 6 16-bit CCT RGBW", 18, "Creamsource")
    csv = b"Fixture Type,DMX Addr,End Addr,Ch\nVortex8 16b RGBW,101,999,18\n"
    mapping = {
        "Fixture Type": "type", "DMX Addr": "address",
        "End Addr": "endAddress", "Ch": "channelCount",
    }
    key = fixture_source_key("Vortex8 16b RGBW", 18)
    resp = client.post(
        f"/api/patch-sheets/{pid}/import/commit",
        data=_import_data(csv, mapping, {key: selected.id}),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert resp.get_json() == {
        "inserted": 1, "skipped": 0, "matchedRows": 1, "unmatchedRows": 0,
    }
    row = PatchRow.query.filter_by(patch_id=pid).one()
    assert row.type == selected.fixture
    assert row.channel_count == 18
    assert row.imported_fixture_type == "Vortex8 16b RGBW"
    assert row.imported_channel_count == 18
    assert row.end_address == 118


def test_commit_preserves_explicitly_unmatched_source_type(client, db):
    pid = _make_patch(db, show_name="T-unmatched")
    csv = b"Fixture Type,DMX Addr,Ch\nMystery Panel,1,12\n"
    mapping = {"Fixture Type": "type", "DMX Addr": "address", "Ch": "channelCount"}
    key = fixture_source_key("Mystery Panel", 12)
    resp = client.post(
        f"/api/patch-sheets/{pid}/import/commit",
        data=_import_data(csv, mapping, {key: None}),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert resp.get_json()["unmatchedRows"] == 1
    assert PatchRow.query.filter_by(patch_id=pid).one().type == "Mystery Panel"


def test_commit_rejects_selection_when_sheet_omits_channel_count(client, db):
    pid = _make_patch(db, show_name="T-missing-footprint")
    selected = _fixture(db, "Custom Profile", 7, "Test Vendor")
    csv = b"Fixture Type,DMX Addr\nUnknown Profile,101\n"
    mapping = {"Fixture Type": "type", "DMX Addr": "address"}
    key = fixture_source_key("Unknown Profile", None)
    resp = client.post(
        f"/api/patch-sheets/{pid}/import/commit",
        data=_import_data(csv, mapping, {key: selected.id}),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "channel count is missing" in resp.get_json()["error"]
    assert PatchRow.query.filter_by(patch_id=pid).count() == 0


def test_commit_keeps_legacy_missing_count_row_when_explicitly_unmatched(client, db):
    pid = _make_patch(db, show_name="T-missing-footprint-unmatched")
    csv = b"Fixture Type,DMX Addr\nUnknown Profile,101\n"
    mapping = {"Fixture Type": "type", "DMX Addr": "address"}
    key = fixture_source_key("Unknown Profile", None)
    resp = client.post(
        f"/api/patch-sheets/{pid}/import/commit",
        data=_import_data(csv, mapping, {key: None}),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    row = PatchRow.query.filter_by(patch_id=pid).one()
    assert row.type == "Unknown Profile"
    assert row.channel_count is None
    assert row.end_address is None


def test_commit_rejects_selected_profile_that_no_longer_exists(client, db):
    pid = _make_patch(db, show_name="T-missing-profile")
    csv = b"Fixture Type,DMX Addr,Ch\nUnknown Profile,1,7\n"
    mapping = {"Fixture Type": "type", "DMX Addr": "address", "Ch": "channelCount"}
    key = fixture_source_key("Unknown Profile", 7)
    resp = client.post(
        f"/api/patch-sheets/{pid}/import/commit",
        data=_import_data(csv, mapping, {key: 999999}),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "no longer exists" in resp.get_json()["error"]
    assert PatchRow.query.filter_by(patch_id=pid).count() == 0


@pytest.mark.parametrize("invalid_id", [True, 1.9, "1"])
def test_commit_rejects_non_integer_selected_fixture_ids(client, db, invalid_id):
    pid = _make_patch(db, show_name=f"T-invalid-id-{invalid_id}")
    csv = b"Fixture Type,DMX Addr,Ch\nUnknown Profile,101,7\n"
    mapping = {"Fixture Type": "type", "DMX Addr": "address", "Ch": "channelCount"}
    key = fixture_source_key("Unknown Profile", 7)
    resp = client.post(
        f"/api/patch-sheets/{pid}/import/commit",
        data=_import_data(csv, mapping, {key: invalid_id}),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Invalid selected fixture ID"
    assert PatchRow.query.filter_by(patch_id=pid).count() == 0


def test_commit_inserts_rows_with_derivation(client, db):
    pid = _make_patch(db)
    csv = b"Fixture Type,DMX Addr,Ch,Dimmer\nPAR64,101,8,full\n"
    mapping = {"Fixture Type": "type", "DMX Addr": "address",
               "Ch": "channelCount", "Dimmer": None}
    data = {
        "file": (io.BytesIO(csv), "foreign.csv"),
        "mapping": json.dumps(mapping),
        "headerRowIndex": "0",
    }
    resp = client.post(f"/api/patch-sheets/{pid}/import/commit",
                       data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["inserted"] == 1
    row = PatchRow.query.filter_by(patch_id=pid).one()
    assert row.type == "PAR64"
    assert row.address == 101
    assert row.end_address == 108      # derived
    assert row.channel_count == 8


def test_commit_truncates_patch_type_but_preserves_full_imported_identity(client, db):
    pid = _make_patch(db, show_name="T-truncate")
    long_type = "X" * 200
    csv = ("Fixture Type,DMX Addr,Ch\n" + long_type + ",101,8\n").encode()
    mapping = {"Fixture Type": "type", "DMX Addr": "address", "Ch": "channelCount"}
    data = {
        "file": (io.BytesIO(csv), "foreign.csv"),
        "mapping": json.dumps(mapping),
        "headerRowIndex": "0",
    }
    resp = client.post(f"/api/patch-sheets/{pid}/import/commit",
                       data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["inserted"] == 1
    row = PatchRow.query.filter_by(patch_id=pid).one()
    assert len(row.type) == 120
    assert row.type == long_type[:120]
    assert row.imported_fixture_type == long_type
    assert row.imported_channel_count == 8
