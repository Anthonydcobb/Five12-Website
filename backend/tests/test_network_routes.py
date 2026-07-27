"""Hostile-input guards on the three PowerShell-executing network routes.

[REVIEW 2026-07-27] /api/network/apply and /api/network/dhcp interpolated the
request-supplied adapter name, IP, and gateway directly into PowerShell source
inside single quotes. A single apostrophe in the adapter name closed the quote
and appended arbitrary PowerShell, and the routes are unauthenticated. These
tests pin the four guards that replaced that: the kill switch, the origin check,
input validation, and parameter passing via the environment instead of the
script text.

PowerShell does not exist on the test machine, so subprocess.run is faked. That
is the point of the fake, not a limitation of it — every assertion here is about
what we *send* to the shell, which is exactly where the defect lived.
"""

import json
from unittest.mock import patch

import pytest


ADAPTERS = ['Ethernet 2', 'Wi-Fi']

# The payload that used to work: the apostrophe terminates -InterfaceAlias '...'
# and everything after it was parsed by PowerShell as new statements.
INJECTION = "Ethernet 2'; Start-Process calc.exe; #"


class FakeCompleted:
    def __init__(self, stdout='', stderr='', returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def fake_ps(calls):
    """subprocess.run stand-in that records every invocation into `calls`."""
    def _run(argv, **kwargs):
        script = argv[-1]
        calls.append({'script': script, 'env': kwargs.get('env') or {}})
        if 'Get-NetAdapter' in script:
            return FakeCompleted(stdout=json.dumps(ADAPTERS))
        return FakeCompleted(stdout='', stderr='', returncode=0)
    return _run


@pytest.fixture
def ps_calls():
    calls = []
    with patch('app.routes.subprocess.run', side_effect=fake_ps(calls)):
        yield calls


def ps_scripts(calls):
    """Only the scripts that actually reconfigure a NIC."""
    return [c['script'] for c in calls if 'Get-NetAdapter' not in c['script']]


# ── Adapter allowlisting ─────────────────────────────────────────────────────

def test_injection_in_adapter_name_is_rejected(client, ps_calls):
    res = client.post('/api/network/apply',
                      json={'adapter': INJECTION, 'ip': '192.168.1.50'})
    assert res.status_code == 400
    assert 'Unknown network adapter' in res.get_json()['error']
    assert ps_scripts(ps_calls) == [], 'no NIC command may run for a bad adapter'


def test_injection_in_adapter_name_is_rejected_on_dhcp(client, ps_calls):
    res = client.post('/api/network/dhcp', json={'adapter': INJECTION})
    assert res.status_code == 400
    assert ps_scripts(ps_calls) == []


def test_unknown_adapter_is_rejected(client, ps_calls):
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 47', 'ip': '192.168.1.50'})
    assert res.status_code == 400
    assert ps_scripts(ps_calls) == []


# ── Address validation ───────────────────────────────────────────────────────

@pytest.mark.parametrize('bad_ip', [
    '192.168.1.999', 'not-an-ip', '192.168.1', '', "10.0.0.1'; calc; #",
])
def test_malformed_ip_is_rejected(client, ps_calls, bad_ip):
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 2', 'ip': bad_ip})
    assert res.status_code == 400
    assert ps_scripts(ps_calls) == []


def test_malformed_gateway_is_rejected(client, ps_calls):
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50',
                            'gateway': "192.168.1.1'; calc; #"})
    assert res.status_code == 400
    assert ps_scripts(ps_calls) == []


@pytest.mark.parametrize('bad_prefix', [0, 33, -1, 'twenty-four'])
def test_out_of_range_prefix_is_rejected(client, ps_calls, bad_prefix):
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50',
                            'prefix': bad_prefix})
    assert res.status_code == 400
    assert ps_scripts(ps_calls) == []


# ── Parameter passing ────────────────────────────────────────────────────────

def test_valid_apply_passes_values_through_the_environment(client, ps_calls):
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50',
                            'prefix': 24, 'gateway': '192.168.1.1'})
    assert res.status_code == 200

    scripts = ps_scripts(ps_calls)
    assert len(scripts) == 1
    script = scripts[0]

    # The operator's values must not appear in the script text at all — that is
    # what makes injection impossible rather than merely difficult.
    assert 'Ethernet 2' not in script
    assert '192.168.1.50' not in script
    assert '192.168.1.1' not in script
    assert '$env:FIVE12_ADAPTER' in script

    env = [c['env'] for c in ps_calls if 'Get-NetAdapter' not in c['script']][0]
    assert env['FIVE12_ADAPTER'] == 'Ethernet 2'
    assert env['FIVE12_IP'] == '192.168.1.50'
    assert env['FIVE12_GATEWAY'] == '192.168.1.1'


def test_valid_dhcp_passes_adapter_through_the_environment(client, ps_calls):
    res = client.post('/api/network/dhcp', json={'adapter': 'Wi-Fi'})
    assert res.status_code == 200

    scripts = ps_scripts(ps_calls)
    assert len(scripts) == 1
    assert 'Wi-Fi' not in scripts[0]
    assert '$env:FIVE12_ADAPTER' in scripts[0]

    env = [c['env'] for c in ps_calls if 'Get-NetAdapter' not in c['script']][0]
    assert env['FIVE12_ADAPTER'] == 'Wi-Fi'


def test_apply_omits_gateway_flag_when_no_gateway_given(client, ps_calls):
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50'})
    assert res.status_code == 200
    assert '-DefaultGateway' not in ps_scripts(ps_calls)[0]


# ── Origin / CSRF ────────────────────────────────────────────────────────────

def test_cross_origin_post_is_rejected(client, ps_calls):
    """A page on the open web must not be able to reconfigure a NIC.

    No CORS is configured, so the browser blocks reading our response but still
    delivers a simple-content-type POST, and get_json(force=True) parses it. For
    a NIC change the side effect is the entire payload, so the unreadable
    response protects nothing — the Origin header has to be checked.
    """
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50'},
                      headers={'Origin': 'https://evil.example'})
    assert res.status_code == 403
    assert ps_scripts(ps_calls) == []


def test_cross_origin_dhcp_is_rejected(client, ps_calls):
    res = client.post('/api/network/dhcp', json={'adapter': 'Wi-Fi'},
                      headers={'Origin': 'https://evil.example'})
    assert res.status_code == 403
    assert ps_scripts(ps_calls) == []


@pytest.mark.parametrize('origin', [
    'http://127.0.0.1:5000', 'http://localhost:5173', 'http://localhost:5000',
])
def test_local_origins_are_allowed(client, ps_calls, origin):
    """The desktop shell and the Vite dev server are first-party."""
    res = client.post('/api/network/dhcp', json={'adapter': 'Wi-Fi'},
                      headers={'Origin': origin})
    assert res.status_code == 200


def test_request_without_origin_is_allowed(client, ps_calls):
    """Electron's main process and curl send no Origin; they must keep working."""
    res = client.post('/api/network/dhcp', json={'adapter': 'Wi-Fi'})
    assert res.status_code == 200


# ── Kill switch ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('path,payload', [
    ('/api/network/apply', {'adapter': 'Ethernet 2', 'ip': '192.168.1.50'}),
    ('/api/network/dhcp', {'adapter': 'Wi-Fi'}),
])
def test_kill_switch_disables_the_powershell_routes(app, client, ps_calls,
                                                    path, payload):
    """FIVE12_NETWORK_TOOLS=0 must reach these routes too.

    They live on the always-registered routes blueprint, not the gated
    network_routes one, so before this change the switch an operator would set
    on a hosted deploy left exactly the PowerShell-executing endpoints alive.
    """
    app.config['ENABLE_NETWORK_TOOLS'] = False
    try:
        res = client.post(path, json=payload)
        assert res.status_code == 404
        assert ps_calls == []
    finally:
        app.config['ENABLE_NETWORK_TOOLS'] = True


def test_kill_switch_disables_interface_listing(app, client, ps_calls):
    app.config['ENABLE_NETWORK_TOOLS'] = False
    try:
        assert client.get('/api/network/interfaces').status_code == 404
        assert ps_calls == []
    finally:
        app.config['ENABLE_NETWORK_TOOLS'] = True


# ── Enumeration failure ──────────────────────────────────────────────────────

def test_apply_fails_closed_when_adapters_cannot_be_listed(client):
    """No adapter list means no allowlist, so the request must not proceed."""
    def _run(argv, **kwargs):
        return FakeCompleted(stdout='', stderr='boom', returncode=1)

    with patch('app.routes.subprocess.run', side_effect=_run):
        res = client.post('/api/network/apply',
                          json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50'})
    assert res.status_code == 500
