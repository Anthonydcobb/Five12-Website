import io

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
