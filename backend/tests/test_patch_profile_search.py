from app.models import Fixture


def test_patch_profile_search_matches_tokens_across_manufacturer_and_name(client, db):
    profile = Fixture(
        manufacturer='ARRI',
        fixture='SkyPanel S60-C Mode 6',
        channel_count=20,
        library_type='type',
    )
    part = Fixture(
        manufacturer='ARRI', fixture='SkyPanel S60-C Mode 6 Cell',
        channel_count=20, library_type='part',
    )
    db.session.add_all([
        profile,
        Fixture(
            manufacturer='ARRI', fixture='SkyPanel S60-C Mode 8',
            channel_count=20, library_type='type',
        ),
        part,
    ])
    db.session.commit()

    resp = client.get(
        '/api/fixture-library/patch-profiles',
        query_string={'q': 'ARRI SkyPanel S60-C Mode 6'},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    ids = {item['id'] for item in body['items']}
    assert profile.id in ids
    selected_item = next(item for item in body['items'] if item['id'] == profile.id)
    assert selected_item['selectionToken'] == profile.selection_token()
    assert part.id not in ids
    assert all('Mode 6' in item['fixture'] for item in body['items'])


def test_patch_profile_search_does_not_expand_punctuation_only_query(client):
    resp = client.get(
        '/api/fixture-library/patch-profiles', query_string={'q': '---'}
    )
    assert resp.status_code == 200
    assert resp.get_json()['total'] == 0
    assert resp.get_json()['items'] == []
