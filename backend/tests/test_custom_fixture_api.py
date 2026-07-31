import pytest

from app.models import Fixture


def test_create_fixture_draft_preserves_database_add_row_workflow(client):
    resp = client.post('/api/fixtures', json={'draft': True})
    assert resp.status_code == 201
    assert resp.get_json()['fixture'] == ''
    assert resp.get_json()['channelCount'] == 0


def test_create_custom_fixture_persists_manufacturer_and_manual_identity(client, db):
    resp = client.post('/api/fixtures', json={
        'manufacturer': 'Anthony Test Co',
        'fixture': 'Mystery Panel Mode A',
        'channelCount': 12,
        'notes': 'Created while reviewing a patch import',
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body['displayName'] == 'Anthony Test Co — Mystery Panel Mode A'
    assert body['channelCount'] == 12
    assert body['librarySource'] is None
    stored = db.session.get(Fixture, body['id'])
    assert stored.manufacturer == 'Anthony Test Co'


@pytest.mark.parametrize('payload, message', [
    ({'fixture': '   ', 'channelCount': 12}, 'name'),
    ({'fixture': 'Bad Zero', 'channelCount': 0}, 'between 1 and 512'),
    ({'fixture': 'Bad Wide', 'channelCount': 513}, 'between 1 and 512'),
    ({'fixture': 'Bad Text', 'channelCount': 'twelve'}, 'integer'),
    ({'fixture': 'Bad Fraction', 'channelCount': 12.5}, 'integer'),
    ({'fixture': 'Bad Bool', 'channelCount': True}, 'integer'),
    ({'fixture': 'X' * 121, 'channelCount': 12}, '120'),
    ({'manufacturer': 'M' * 121, 'fixture': 'Bad Mfr', 'channelCount': 12}, '120'),
])
def test_create_custom_fixture_rejects_invalid_identity(client, payload, message):
    resp = client.post('/api/fixtures', json=payload)
    assert resp.status_code == 400
    assert message in resp.get_json()['error']


def test_create_custom_fixture_rejects_exact_duplicate(client, db):
    existing = Fixture(
        manufacturer='Duplicate Test Co',
        fixture='Duplicate Profile',
        channel_count=14,
    )
    db.session.add(existing)
    db.session.commit()
    resp = client.post('/api/fixtures', json={
        'manufacturer': 'duplicate test co',
        'fixture': 'duplicate profile',
        'channelCount': 14,
    })
    assert resp.status_code == 409
    assert resp.get_json()['existing']['id'] == existing.id


def test_create_custom_fixture_does_not_treat_internal_part_as_duplicate(client, db):
    part = Fixture(
        manufacturer='Part Test Co',
        fixture='Emitter Cell',
        channel_count=6,
        library_type='part',
    )
    db.session.add(part)
    db.session.commit()
    resp = client.post('/api/fixtures', json={
        'manufacturer': 'Part Test Co',
        'fixture': 'Emitter Cell',
        'channelCount': 6,
    })
    assert resp.status_code == 201
    assert resp.get_json()['id'] != part.id
    assert resp.get_json()['libraryType'] is None
