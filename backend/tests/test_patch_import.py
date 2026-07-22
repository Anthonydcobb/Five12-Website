from app.patch_import import normalize_header, guess_field, guess_mapping, detect_header_row, parse_int, derive_row, apply_mapping

def test_normalize_header_strips_punct_and_case():
    assert normalize_header("Fix #") == "fix"
    assert normalize_header("ch. Count") == "ch count"
    assert normalize_header("  DMX Addr ") == "dmx addr"
    assert normalize_header(None) == ""

def test_guess_field_exact_and_alias():
    assert guess_field("Fixture Type") == "type"
    assert guess_field("DMX Addr") == "address"
    assert guess_field("Ch") == "channelCount"
    assert guess_field("Position") == "location"
    assert guess_field("End Add") == "endAddress"

def test_guess_field_ambiguous_calls():
    # bare "Fixture" -> type (model), bare "Fix #"/"Unit" -> fixture number
    assert guess_field("Fixture") == "type"
    assert guess_field("Unit") == "fixture"
    assert guess_field("Dimmer") is None

def test_guess_mapping():
    m = guess_mapping(["Fixture Type", "DMX Addr", "Ch", "Dimmer"])
    assert m == {"Fixture Type": "type", "DMX Addr": "address",
                 "Ch": "channelCount", "Dimmer": None}

def test_detect_header_row_first_row():
    grid = [["Fix #", "Uni", "Add", "Fix Type"], ["1", "1", "1", "PAR"]]
    assert detect_header_row(grid) == 0

def test_detect_header_row_with_title_rows_above():
    grid = [
        ["My Show Patch", None, None, None],
        [None, None, None, None],
        ["Fix #", "Universe", "Address", "Fixture Type"],
        ["1", "1", "1", "PAR"],
    ]
    assert detect_header_row(grid) == 2

def test_detect_header_row_fallback_zero():
    grid = [["a", "b"], ["c", "d"]]
    assert detect_header_row(grid) == 0

def test_parse_int_handles_floats_and_junk():
    assert parse_int("101") == 101
    assert parse_int(101.0) == 101       # pandas gives floats
    assert parse_int("") is None
    assert parse_int("n/a") is None
    assert parse_int(None) is None

def test_derive_end_from_count():
    r = derive_row({"address": "101", "channelCount": "8"})
    assert r["address"] == 101 and r["channelCount"] == 8
    assert r["endAddress"] == 108

def test_derive_count_from_end():
    r = derive_row({"address": "1", "endAddress": "13"})
    assert r["channelCount"] == 13

def test_derive_does_not_overwrite_provided():
    r = derive_row({"address": "1", "endAddress": "20", "channelCount": "5"})
    assert r["endAddress"] == 20 and r["channelCount"] == 5

def test_clean_str_wattage_float_to_int_string():
    r = derive_row({"wattage": 400.0, "weight": "34.2"})
    assert r["wattage"] == "400" and r["weight"] == "34.2"

def test_apply_mapping_ignores_unmatched_columns():
    headers = ["Fix Type", "Add", "Ch", "Dimmer"]
    mapping = {"Fix Type": "type", "Add": "address", "Ch": "channelCount",
               "Dimmer": None}
    rows = [["PAR64", "101", "8", "full"]]
    out = apply_mapping(headers, rows, mapping)
    assert out == [{"set": None, "fixture": None, "universe": None,
                    "address": 101, "endAddress": 108, "type": "PAR64",
                    "channelCount": 8, "location": None, "wattage": None,
                    "weight": None, "firmware": None, "notes": None}]

def test_apply_mapping_skips_blank_rows():
    headers = ["Fix Type", "Add"]
    mapping = {"Fix Type": "type", "Add": "address"}
    rows = [["PAR", "1"], [None, None], ["", ""]]
    out = apply_mapping(headers, rows, mapping)
    assert len(out) == 1 and out[0]["type"] == "PAR"

def test_apply_mapping_ignore_keyword():
    headers = ["Add", "Junk"]
    out = apply_mapping(headers, [["5", "x"]], {"Add": "address", "Junk": "ignore"})
    assert out[0]["address"] == 5 and out[0]["type"] is None
