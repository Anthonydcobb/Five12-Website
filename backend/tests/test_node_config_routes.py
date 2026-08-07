"""The /api/nodes/<ip>/config routes are gone. /api/nodes/scan stays.

Both config routes were written against HTTP contracts nobody verified, and
both were confirmed wrong against the rig on 2026-08-06:

  GigaCore — an Ethernet switch. Its twelve ports are RJ45 and carry no DMX,
  so there was never a universe to read or set. The code also expected a JSON
  login endpoint returning a bearer token, while the device answers every
  path — including ones that do not exist, like /rest — with
  `401 WWW-Authenticate: Basic realm="GigaCore12"`.

  Swisson XND — genuinely has DMX ports with universes, but the read scraped
  `port_N_universe value="..."` out of the device's HTML, and the XND is a
  JavaScript app that renders from /model/*. The values were never in the
  markup: the endpoint returned `{"allFields": {}}` every time. The write
  POSTed a form to http://<ip>/config, which answers 404.

Their own docstrings said "verify first" and "may need adjustment". Reading a
Swisson's ports is solved elsewhere — `vendors.read_port_status` over
/model/status, which the Network tab's DMX table uses. Writing one is a real
feature that would target a live DMX node and needs designing, not a guessed
form POST.
"""

import pytest


def _rules(app, path):
    return [r for r in app.url_map.iter_rules() if r.rule == path]


def test_the_node_config_routes_are_not_registered(app):
    """Asserted against the url_map rather than an HTTP status on purpose.

    A catch-all in routes.py serves the built SPA for GET on any unmatched
    path, so a plain `assert response.status_code == 404` would pass whether
    or not the route existed — and would pass for the wrong reason once the
    frontend is built. Ask the router directly.
    """
    assert _rules(app, '/api/nodes/<ip>/config') == []


def test_the_node_scan_route_survives(app):
    """The scanner is the working half of that page: ARP cache, Ubiquiti UDP
    discovery, HTTP probes, reverse DNS and health checks — 100 devices in
    ~3s on this rig. Removing the config routes must not touch it."""
    rules = _rules(app, '/api/nodes/scan')
    assert len(rules) == 1
    assert 'GET' in rules[0].methods


def test_no_device_config_helper_survives_in_the_module():
    """Pinned by name so that reviving either approach is a deliberate act
    rather than a paste. Both were guesses at contracts that do not exist."""
    from app import routes
    import inspect

    src = inspect.getsource(routes)
    for gone in ('_gigacore_read', '_gigacore_write',
                 '_swisson_read', '_swisson_write',
                 '_XND_PORT_RE', '_XND_PROTO_RE'):
        assert gone not in src, f'{gone} survived the removal'


@pytest.mark.parametrize('verb', ['get', 'put'])
def test_reaching_the_old_config_path_never_touches_a_node(client, verb):
    """Whatever the router does with the old path now — SPA fallback on GET,
    405 on PUT — the one thing that must not happen is an HTTP request going
    out to the device. The rig is live and the PUT half used to carry a
    universe change."""
    import app.routes as routes

    assert not hasattr(routes, '_swisson_write')
    res = getattr(client, verb)('/api/nodes/10.31.8.51/config')
    assert res.status_code in (404, 405)
