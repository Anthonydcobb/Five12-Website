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

import io

def _upload(client, xml=SAMPLE, name='Fixture Tag'):
    return client.post('/api/dymo-templates',
                       data={'file': (io.BytesIO(xml.encode()), 'tag.dymo'),
                             'name': name},
                       content_type='multipart/form-data')

def test_upload_and_list_roundtrip(client, db):
    r = _upload(client)
    assert r.status_code == 201
    body = r.get_json()
    assert body['name'] == 'Fixture Tag'
    assert body['variables'] == ['FixNum', 'Uni']
    lst = client.get('/api/dymo-templates').get_json()
    assert any(t['id'] == body['id'] for t in lst)
    assert 'labelXml' not in lst[0]
    one = client.get(f"/api/dymo-templates/{body['id']}").get_json()
    assert one['labelXml'].startswith('<?xml')

def test_upload_rejects_no_variables(client, db):
    xml = '<DesktopLabel><DYMOLabel/></DesktopLabel>'
    r = _upload(client, xml=xml, name='empty')
    assert r.status_code == 400
    assert 'named' in r.get_json()['error']

def test_upload_rejects_bad_xml(client, db):
    assert _upload(client, xml='<<<', name='bad').status_code == 400

def test_saved_mapping_put_and_merge(client, db):
    tid = _upload(client, name='MapMe').get_json()['id']
    r = client.put(f'/api/dymo-templates/{tid}/mapping',
                   json={'source': 'patch', 'mapping': {'FixNum': 'fixture'}})
    assert r.status_code == 200
    r = client.put(f'/api/dymo-templates/{tid}/mapping',
                   json={'source': 'csv', 'mapping': {'Uni': 'Universe Col'}})
    got = client.get(f'/api/dymo-templates/{tid}').get_json()['savedMappings']
    assert got == {'patch': {'FixNum': 'fixture'}, 'csv': {'Uni': 'Universe Col'}}

def test_delete(client, db):
    tid = _upload(client, name='Gone').get_json()['id']
    assert client.delete(f'/api/dymo-templates/{tid}').status_code == 200
    assert all(t['id'] != tid for t in client.get('/api/dymo-templates').get_json())

def test_upload_keeps_dots_in_explicit_name(client, db):
    r = _upload(client, name='Rig 2.1')
    assert r.status_code == 201
    assert r.get_json()['name'] == 'Rig 2.1'

def test_upload_strips_extension_from_filename_fallback(client, db):
    r = client.post('/api/dymo-templates',
                    data={'file': (io.BytesIO(SAMPLE.encode()), 'cable wrap.dymo')},
                    content_type='multipart/form-data')
    assert r.status_code == 201
    assert r.get_json()['name'] == 'cable wrap'

def test_upload_tolerates_utf8_bom(client, db):
    r = _upload(client, xml='﻿' + SAMPLE, name='BOM Tag')
    assert r.status_code == 201
    assert r.get_json()['variables'] == ['FixNum', 'Uni']
