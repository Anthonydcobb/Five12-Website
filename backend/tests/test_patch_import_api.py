import io, json
from app import db
from app.models import Show, PatchSheet, PatchRow

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


def _make_patch(db):
    show = Show(name="T")
    db.session.add(show); db.session.commit()
    sheet = PatchSheet(name="U", show_id=show.id)
    db.session.add(sheet); db.session.commit()
    return sheet.id

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
