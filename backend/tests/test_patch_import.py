from app.patch_import import normalize_header, guess_field, guess_mapping

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
