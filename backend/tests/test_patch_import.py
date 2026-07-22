from app.patch_import import normalize_header, guess_field, guess_mapping, detect_header_row

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
