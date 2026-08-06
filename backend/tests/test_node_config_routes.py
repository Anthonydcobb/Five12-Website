"""The /api/nodes/<ip>/config routes, and the GigaCore path that was removed.

These routes had NO test coverage at all, which is how a dead configuration
path survived long enough to be offered in the UI. The GigaCore branch tried
to set `universe` / `protocol` / `mergeMode` on a Luminex GigaCore — an
Ethernet switch with no DMX ports and therefore no universes — via a bearer
token obtained from a JSON login endpoint.

It was wrong twice over, confirmed against the rig on 2026-08-06:

  * Wrong data model. A GigaCore12 has twelve RJ45 network ports. Nothing
    about a universe applies to them.
  * Wrong auth model. Every path on the device — including ones that
    certainly do not exist, like /rest and /api/v1 — answers
    `401 WWW-Authenticate: Basic realm="GigaCore12"`. That is a blanket HTTP
    Basic challenge at the web root, not a token-issuing login endpoint.

The Swisson branch is real and must keep working: an XND node genuinely does
have DMX ports with universes, and `_swisson_write` targets them.
"""

from unittest.mock import patch


def test_a_gigacore_read_is_refused_rather_than_attempted(client):
    """A switch has no universes to report. Refusing is the honest answer;
    attempting would reach a live show switch to ask a meaningless question."""
    res = client.get('/api/nodes/172.16.1.21/config?type=gigacore')
    assert res.status_code == 400
    assert 'Unknown device type' in res.get_json()['error']


def test_a_gigacore_write_is_refused_rather_than_attempted(client):
    """The important half. This route PUT `universe`/`protocol`/`mergeMode`
    at a GigaCore, and the rig is live — the operator's standing instruction
    is that nothing may change a switch's ports or settings."""
    res = client.put('/api/nodes/172.16.1.21/config', json={
        'type': 'gigacore', 'portId': 1, 'universe': 5,
        'protocol': 'sacn', 'mergeMode': 'htp',
    })
    assert res.status_code == 400
    assert 'Unknown device type' in res.get_json()['error']


def test_no_gigacore_helper_survives_in_the_module():
    """Pinned by name so that reviving the old approach is a deliberate act
    rather than a paste. A real GigaCore configuration feature would target
    Groups, PoE and port enable over HTTP Basic — not this."""
    from app import routes
    import inspect

    src = inspect.getsource(routes)
    assert '_gigacore_read' not in src
    assert '_gigacore_write' not in src


def test_the_swisson_read_path_is_untouched(client):
    """An XND genuinely has DMX ports with universes. Removing the GigaCore
    branch must not disturb the branch that works."""
    with patch('app.routes._swisson_read', return_value={'ports': [{'id': 1}]}) as rd:
        res = client.get('/api/nodes/10.31.8.51/config?type=swisson')

    assert res.status_code == 200
    assert res.get_json() == {'ports': [{'id': 1}]}
    rd.assert_called_once()


def test_the_swisson_write_path_is_untouched(client):
    with patch('app.routes._swisson_write', return_value=(True, '')) as wr:
        res = client.put('/api/nodes/10.31.8.51/config', json={
            'type': 'swisson', 'portId': 1, 'universe': 5,
        })

    assert res.status_code == 200
    assert res.get_json() == {'success': True}
    wr.assert_called_once()


def test_an_unknown_device_type_is_still_refused(client):
    res = client.get('/api/nodes/10.31.8.51/config?type=banana')
    assert res.status_code == 400
