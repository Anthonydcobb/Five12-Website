import pytest

from app.patch_import import (
    normalize_header, guess_field, guess_mapping, detect_header_row, parse_int,
    derive_row, apply_mapping, fixture_source_key, group_fixture_sources,
    rank_fixture_candidates,
)

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
    assert parse_int("12.5") is None
    assert parse_int("") is None
    assert parse_int("n/a") is None
    assert parse_int(None) is None


def test_derive_rejects_fractional_channel_count():
    with pytest.raises(ValueError, match="whole number"):
        derive_row({"address": "1", "channelCount": "12.5"})

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


def test_fixture_source_key_normalizes_spelling_but_keeps_footprints_distinct():
    assert fixture_source_key("ARRI  SkyPanel S60-C / Mode 6", 20) == \
        fixture_source_key("arri skypanel s60 c mode 6", 20)
    assert fixture_source_key("ARRI SkyPanel S60-C Mode 6", 20) != \
        fixture_source_key("ARRI SkyPanel S60-C Mode 6", 18)


def test_fixture_source_key_preserves_numeric_mode_punctuation():
    assert fixture_source_key("Panel Mode 1.2", 12) != \
        fixture_source_key("Panel Mode 1-2", 12)
    assert fixture_source_key("Panel Mode 1-2", 12) != \
        fixture_source_key("Panel Mode 1/2", 12)


def test_group_fixture_sources_collapses_repeated_fixture_rows():
    groups = group_fixture_sources([
        {"type": "Vortex8 16b RGBW", "channelCount": 18},
        {"type": "vortex8 16B-RGBW", "channelCount": 18},
        {"type": "Mystery Panel", "channelCount": 12},
        {"type": None, "channelCount": 1},
    ])
    assert groups == [
        {
            "key": fixture_source_key("Vortex8 16b RGBW", 18),
            "sourceType": "Vortex8 16b RGBW",
            "channelCount": 18,
            "rowCount": 2,
        },
        {
            "key": fixture_source_key("Mystery Panel", 12),
            "sourceType": "Mystery Panel",
            "channelCount": 12,
            "rowCount": 1,
        },
    ]


def test_rank_fixture_candidates_requires_exact_channel_count():
    candidates = [
        {"id": 1, "manufacturer": "ARRI", "fixture": "SkyPanel S60-C Mode 6", "channelCount": 20},
        {"id": 2, "manufacturer": "ARRI", "fixture": "SkyPanel S60-C Mode 6", "channelCount": 18},
    ]
    ranked = rank_fixture_candidates("ARRI SkyPanel S60 Mode 6", 20, candidates)
    assert [item["id"] for item in ranked] == [1]


def test_rank_fixture_candidates_marks_only_normalized_exact_names_exact():
    candidates = [
        {"id": 1, "manufacturer": "ARRI", "fixture": "SkyPanel S60-C Mode 6", "channelCount": 20},
        {"id": 2, "manufacturer": "ARRI", "fixture": "SkyPanel S60-C Mode 8", "channelCount": 20},
    ]
    ranked = rank_fixture_candidates("ARRI — SkyPanel S60-C Mode 6", 20, candidates)
    assert ranked[0]["id"] == 1
    assert ranked[0]["exact"] is True
    assert ranked[1]["exact"] is False


def test_rank_fixture_candidates_does_not_auto_exact_distinct_mode_punctuation():
    candidates = [{
        "id": 1, "manufacturer": "Test", "fixture": "Panel Mode 1-2",
        "channelCount": 12,
    }]
    ranked = rank_fixture_candidates("Test Panel Mode 1.2", 12, candidates)
    assert ranked[0]["id"] == 1
    assert ranked[0]["exact"] is False


def test_rank_fixture_candidates_uses_mode_tokens_to_rank_close_names():
    candidates = [
        {"id": 1, "manufacturer": "Creamsource", "fixture": "Vortex8 Mode 6 16-bit CCT RGBW", "channelCount": 18},
        {"id": 2, "manufacturer": "Creamsource", "fixture": "Vortex8 Mode 8 HSI", "channelCount": 18},
    ]
    ranked = rank_fixture_candidates("Vortex 8 mode 6 16b RGBW", 18, candidates)
    assert ranked[0]["id"] == 1
    assert ranked[0]["score"] > ranked[1]["score"]


import pandas as pd
from io import BytesIO
from app.patch_import import read_table

def _xlsx_bytes(rows):
    bio = BytesIO()
    pd.DataFrame(rows).to_excel(bio, header=False, index=False, engine="openpyxl")
    return bio.getvalue()

def test_read_table_csv():
    data = b"Fix Type,Add,Ch\nPAR64,101,8\n"
    grid = read_table(data, "foreign.csv")
    assert grid[0] == ["Fix Type", "Add", "Ch"]
    assert grid[1][0] == "PAR64"

def test_read_table_xlsx_parity():
    data = _xlsx_bytes([["Fix Type", "Add", "Ch"], ["PAR64", 101, 8]])
    grid = read_table(data, "foreign.xlsx")
    assert grid[0] == ["Fix Type", "Add", "Ch"]
    assert grid[1][0] == "PAR64"

def test_read_table_blank_cells_are_none():
    grid = read_table(b"a,,c\n1,,3\n", "x.csv")
    assert grid[1][1] is None
