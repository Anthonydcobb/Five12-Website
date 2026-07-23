def _post(client, name='rig.csv', headers=None, rows=None):
    headers = ['A', 'B'] if headers is None else headers
    rows = ([{'A': '1', 'B': 'x'}, {'A': '2', 'B': 'y'}] if rows is None else rows)
    return client.post('/api/dymo-csv-sources',
                       json={'name': name, 'headers': headers, 'rows': rows})

def test_post_inserts_with_server_row_count(client, db):
    r = _post(client, rows=[{'A': '1'}, {'A': '2'}, {'A': '3'}])
    assert r.status_code == 201
    body = r.get_json()
    assert body['name'] == 'rig.csv'
    assert body['rowCount'] == 3          # computed server-side
    assert 'rows' not in body             # list-shape omits rows

def test_list_omits_rows_get_one_includes(client, db):
    sid = _post(client).get_json()['id']
    lst = client.get('/api/dymo-csv-sources').get_json()
    assert any(e['id'] == sid for e in lst)
    assert all('rows' not in e for e in lst)
    one = client.get(f'/api/dymo-csv-sources/{sid}').get_json()
    assert one['rows'] == [{'A': '1', 'B': 'x'}, {'A': '2', 'B': 'y'}]

def test_upsert_by_name_updates_in_place(client, db):
    first = _post(client, name='same.csv', rows=[{'A': '1'}]).get_json()
    second = _post(client, name='same.csv', rows=[{'A': '9'}, {'A': '8'}]).get_json()
    assert second['id'] == first['id']    # same row, updated
    lst = client.get('/api/dymo-csv-sources').get_json()
    assert len([e for e in lst if e['name'] == 'same.csv']) == 1
    assert client.get(f"/api/dymo-csv-sources/{first['id']}").get_json()['rows'] == [{'A': '9'}, {'A': '8'}]

def test_auto_cap_keeps_20_newest(client, db):
    for i in range(21):
        _post(client, name=f'f{i}.csv')
    lst = client.get('/api/dymo-csv-sources').get_json()
    assert len(lst) == 20
    names = {e['name'] for e in lst}
    assert 'f0.csv' not in names          # oldest dropped
    assert 'f20.csv' in names

def test_list_is_newest_first(client, db):
    _post(client, name='old.csv')
    _post(client, name='new.csv')
    lst = client.get('/api/dymo-csv-sources').get_json()
    assert lst[0]['name'] == 'new.csv'

def test_delete(client, db):
    sid = _post(client, name='gone.csv').get_json()['id']
    assert client.delete(f'/api/dymo-csv-sources/{sid}').status_code == 200
    assert all(e['id'] != sid for e in client.get('/api/dymo-csv-sources').get_json())
    assert client.delete(f'/api/dymo-csv-sources/{sid}').status_code == 404

def test_post_validation(client, db):
    assert client.post('/api/dymo-csv-sources', json={'name': '', 'headers': [], 'rows': []}).status_code == 400
    assert client.post('/api/dymo-csv-sources', json={'name': 'x', 'headers': 'no', 'rows': []}).status_code == 400
    assert client.post('/api/dymo-csv-sources', json={'name': 'x', 'headers': [], 'rows': 'no'}).status_code == 400
