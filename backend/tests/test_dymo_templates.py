import pytest
from app.dymo_templates import extract_variables

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<DesktopLabel Version="1">
  <DYMOLabel Version="3">
    <ObjectInfo><TextObject><Name>FixNum</Name><Text>101</Text></TextObject></ObjectInfo>
    <ObjectInfo><TextObject><Name>Uni</Name><Text>1</Text></TextObject></ObjectInfo>
    <ObjectInfo><TextObject><Name></Name><Text>static</Text></TextObject></ObjectInfo>
    <ObjectInfo><BarcodeObject><Name>Code</Name></BarcodeObject></ObjectInfo>
    <ObjectInfo><TextObject><Name>FixNum</Name><Text>dup</Text></TextObject></ObjectInfo>
  </DYMOLabel>
</DesktopLabel>"""

def test_extracts_named_text_objects_in_order_deduped():
    assert extract_variables(SAMPLE) == ["FixNum", "Uni"]

def test_barcode_and_unnamed_objects_ignored():
    assert "Code" not in extract_variables(SAMPLE)

def test_invalid_xml_raises():
    with pytest.raises(ValueError):
        extract_variables("not xml at all <<<")

def test_no_variables_returns_empty():
    xml = '<DesktopLabel><DYMOLabel><ObjectInfo><TextObject><Name></Name></TextObject></ObjectInfo></DYMOLabel></DesktopLabel>'
    assert extract_variables(xml) == []
