"""Guards on the three privileged network routes.

[REVIEW 2026-07-27] /api/network/apply and /api/network/dhcp interpolated the
request-supplied adapter name, IP and gateway straight into PowerShell source
inside single quotes. One apostrophe in the adapter name closed the quote and
appended arbitrary PowerShell, on unauthenticated endpoints that reconfigure a
NIC as administrator.

[BENCH 2026-07-28] The first fix moved those values into the child process
environment. That held on real PowerShell, but New-NetIPAddress turned out to be
unable to configure a *disconnected* adapter at all — Windows error 87, because
it writes to the persistent store while the interface still reports DHCP, and
the persistent store returns an empty Dhcp that Set-NetIPInterface cannot
change. netsh does the same job atomically and succeeded on the same adapter.

So the two writes now go through netsh with the operator's values as separate
argument-vector entries. That is the stronger guarantee, not a fallback: there
is no shell and no script text, so nothing can be parsed as code. Reads still
use PowerShell and never take operator input.

Neither netsh nor PowerShell exists on the test machine, so subprocess.run is
faked. Every assertion here is about *what we hand to the OS*, which is exactly
where the original defect lived. Whether Windows then behaves is a bench
question these tests cannot and do not answer.
"""

import json
from unittest.mock import patch

import pytest


ADAPTERS = ['Ethernet 2', 'Wi-Fi']

# The payload that used to work against the interpolated PowerShell.
INJECTION = "Ethernet 2'; Start-Process calc.exe; #"

# An injection-shaped name the machine genuinely has. Windows permits
# apostrophes in adapter aliases, so this is a legitimate rename.
HOSTILE_ALIAS_INVENTORY = ['Ethernet 2', INJECTION]


class FakeCompleted:
    def __init__(self, stdout='', stderr='', returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def fake_shell(calls, adapters=None, netsh=None):
    """subprocess.run stand-in recording every invocation into `calls`.

    PowerShell calls serve the adapter inventory; netsh calls are the writes.
    """
    inventory = ADAPTERS if adapters is None else adapters

    def _run(argv, **kwargs):
        argv = list(argv)
        calls.append({'argv': argv, 'kwargs': kwargs})
        if argv and argv[0] == 'netsh':
            return netsh or FakeCompleted()
        return FakeCompleted(stdout=json.dumps(inventory))
    return _run


@pytest.fixture
def shell():
    calls = []
    with patch('app.routes.subprocess.run', side_effect=fake_shell(calls)):
        yield calls


@pytest.fixture
def shell_hostile_inventory():
    calls = []
    with patch('app.routes.subprocess.run',
               side_effect=fake_shell(calls, adapters=HOSTILE_ALIAS_INVENTORY)):
        yield calls


def netsh_calls(calls):
    """Only the invocations that actually reconfigure a NIC."""
    return [c for c in calls if c['argv'] and c['argv'][0] == 'netsh']


# ── Adapter allowlisting ─────────────────────────────────────────────────────

def test_injection_in_adapter_name_is_rejected(client, shell):
    res = client.post('/api/network/apply',
                      json={'adapter': INJECTION, 'ip': '192.168.1.50'})
    assert res.status_code == 400
    assert 'Unknown network adapter' in res.get_json()['error']
    assert netsh_calls(shell) == [], 'no NIC command may run for a bad adapter'


def test_injection_in_adapter_name_is_rejected_on_dhcp(client, shell):
    res = client.post('/api/network/dhcp', json={'adapter': INJECTION})
    assert res.status_code == 400
    assert netsh_calls(shell) == []


def test_unknown_adapter_is_rejected(client, shell):
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 47', 'ip': '192.168.1.50'})
    assert res.status_code == 400
    assert netsh_calls(shell) == []


# ── Address validation ───────────────────────────────────────────────────────

@pytest.mark.parametrize('bad_ip', [
    '192.168.1.999', 'not-an-ip', '192.168.1', '', "10.0.0.1'; calc; #",
])
def test_malformed_ip_is_rejected(client, shell, bad_ip):
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 2', 'ip': bad_ip})
    assert res.status_code == 400
    assert netsh_calls(shell) == []


def test_malformed_gateway_is_rejected(client, shell):
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50',
                            'gateway': "192.168.1.1'; calc; #"})
    assert res.status_code == 400
    assert netsh_calls(shell) == []


@pytest.mark.parametrize('bad_prefix', [0, 33, -1, 'twenty-four'])
def test_out_of_range_prefix_is_rejected(client, shell, bad_prefix):
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50',
                            'prefix': bad_prefix})
    assert res.status_code == 400
    assert netsh_calls(shell) == []


# ── Argument-vector transport ────────────────────────────────────────────────

def test_apply_passes_values_as_separate_argv_entries(client, shell):
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50',
                            'prefix': 24, 'gateway': '192.168.1.1'})
    assert res.status_code == 200

    calls = netsh_calls(shell)
    assert len(calls) == 1
    argv = calls[0]['argv']

    assert argv[:5] == ['netsh', 'interface', 'ipv4', 'set', 'address']
    assert 'name=Ethernet 2' in argv
    assert '192.168.1.50' in argv
    assert '255.255.255.0' in argv, 'prefix 24 must become a dotted mask'
    assert '192.168.1.1' in argv

    # No shell anywhere: nothing can reinterpret these as syntax.
    assert calls[0]['kwargs'].get('shell') in (None, False)


def test_apply_omits_gateway_when_not_given(client, shell):
    client.post('/api/network/apply',
                json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50'})
    argv = netsh_calls(shell)[0]['argv']
    assert argv[-1] == '255.255.255.0', 'nothing should follow the mask'


@pytest.mark.parametrize('prefix,mask', [
    (8, '255.0.0.0'), (16, '255.255.0.0'), (24, '255.255.255.0'),
    (30, '255.255.255.252'), (32, '255.255.255.255'),
])
def test_prefix_converts_to_the_right_mask(client, shell, prefix, mask):
    client.post('/api/network/apply',
                json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50',
                      'prefix': prefix})
    assert mask in netsh_calls(shell)[0]['argv']


def test_dhcp_passes_adapter_as_an_argv_entry(client, shell):
    res = client.post('/api/network/dhcp', json={'adapter': 'Wi-Fi'})
    assert res.status_code == 200
    argv = netsh_calls(shell)[0]['argv']
    assert 'name=Wi-Fi' in argv
    assert 'source=dhcp' in argv


def test_allowlisted_hostile_alias_is_delivered_verbatim_as_data(
        client, shell_hostile_inventory):
    """An injection-shaped name the machine really has must still be inert.

    This is the load-bearing test: the allowlist passes the value through, so
    the argument-vector transport is the only thing between it and the OS.
    """
    res = client.post('/api/network/apply',
                      json={'adapter': INJECTION, 'ip': '192.168.1.50',
                            'prefix': 24, 'gateway': '192.168.1.1'})
    assert res.status_code == 200, 'a real adapter must be accepted'

    calls = netsh_calls(shell_hostile_inventory)
    assert len(calls) == 1
    argv, kwargs = calls[0]['argv'], calls[0]['kwargs']

    # The whole value arrives as exactly one argument, unsplit and unescaped...
    assert f'name={INJECTION}' in argv
    # ...and no element is a shell fragment carrying the payload onward.
    assert not any(a for a in argv if a.startswith('Start-Process'))
    assert kwargs.get('shell') in (None, False), 'a shell would reopen the hole'


def test_allowlisted_hostile_alias_is_inert_on_dhcp(
        client, shell_hostile_inventory):
    res = client.post('/api/network/dhcp', json={'adapter': INJECTION})
    assert res.status_code == 200
    call = netsh_calls(shell_hostile_inventory)[0]
    assert f'name={INJECTION}' in call['argv']
    assert call['kwargs'].get('shell') in (None, False)


# ── Origin / CSRF ────────────────────────────────────────────────────────────

def test_cross_origin_post_is_rejected(client, shell):
    """A page on the open web must not be able to reconfigure a NIC.

    No CORS is configured, so the browser blocks reading our response but still
    delivers a simple-content-type POST, and get_json(force=True) parses it. For
    a NIC change the side effect is the whole payload.
    """
    res = client.post('/api/network/apply',
                      json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50'},
                      headers={'Origin': 'https://evil.example'})
    assert res.status_code == 403
    assert netsh_calls(shell) == []


def test_cross_origin_dhcp_is_rejected(client, shell):
    res = client.post('/api/network/dhcp', json={'adapter': 'Wi-Fi'},
                      headers={'Origin': 'https://evil.example'})
    assert res.status_code == 403
    assert netsh_calls(shell) == []


@pytest.mark.parametrize('origin', [
    'http://127.0.0.1:5000', 'http://localhost:5173', 'http://127.0.0.1:5050',
    'http://localhost:5000', 'http://[::1]:5173',
])
def test_local_origins_are_allowed(client, shell, origin):
    """Electron's renderer, the Vite dev server and direct Flask are all local."""
    res = client.post('/api/network/dhcp', json={'adapter': 'Wi-Fi'},
                      headers={'Origin': origin})
    assert res.status_code == 200


def test_request_without_origin_is_allowed(client, shell):
    """curl and other native callers send no Origin; they must keep working."""
    assert client.post('/api/network/dhcp',
                       json={'adapter': 'Wi-Fi'}).status_code == 200


# ── Kill switch ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('path,payload', [
    ('/api/network/apply', {'adapter': 'Ethernet 2', 'ip': '192.168.1.50'}),
    ('/api/network/dhcp', {'adapter': 'Wi-Fi'}),
])
def test_kill_switch_disables_the_privileged_routes(app, client, shell,
                                                    path, payload):
    """FIVE12_NETWORK_TOOLS=0 must reach these routes too.

    They live on the always-registered routes blueprint, not the gated
    network_routes one, so before this change the switch an operator would set
    on a hosted deploy left exactly the privileged endpoints alive.
    """
    app.config['ENABLE_NETWORK_TOOLS'] = False
    try:
        assert client.post(path, json=payload).status_code == 404
        assert shell == []
    finally:
        app.config['ENABLE_NETWORK_TOOLS'] = True


def test_kill_switch_disables_interface_listing(app, client, shell):
    app.config['ENABLE_NETWORK_TOOLS'] = False
    try:
        assert client.get('/api/network/interfaces').status_code == 404
        assert shell == []
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


# ── Failure reporting ────────────────────────────────────────────────────────
#
# [BENCH 2026-07-28] The rig hit /api/network/dhcp returning exactly
# {"error": "DHCP switch failed", "adminRequired": false} — the child exited
# non-zero having written nothing to stderr, and the route forwarded stderr
# alone, so everything diagnostic was discarded. The operator got a failure with
# nothing to act on, and so did whoever had to debug it.

def post_dhcp_failing(client, **kwargs):
    calls = []
    fake = fake_shell(calls, netsh=FakeCompleted(**kwargs))
    with patch('app.routes.subprocess.run', side_effect=fake):
        return client.post('/api/network/dhcp', json={'adapter': 'Wi-Fi'})


def test_silent_failure_still_reports_the_exit_code(client):
    """The exact rig case: non-zero exit, nothing on stderr or stdout."""
    res = post_dhcp_failing(client, returncode=1)
    assert res.status_code == 500
    error = res.get_json()['error']
    assert 'exited 1' in error, f'no exit code in operator message: {error!r}'
    assert error != 'DHCP switch failed', 'bare fallback carries no information'


def test_stdout_is_used_when_stderr_is_empty(client):
    """netsh reports its errors on stdout, so stderr alone is not enough."""
    res = post_dhcp_failing(client, stdout='The filename is invalid.',
                            returncode=1)
    assert 'The filename is invalid.' in res.get_json()['error']


def test_stderr_still_wins_when_present(client):
    res = post_dhcp_failing(client, stdout='noise', stderr='real cause',
                            returncode=1)
    assert 'real cause' in res.get_json()['error']


def test_access_denied_is_reported_as_admin_required(client):
    """The rig's failure before elevation — must stay a 403."""
    res = post_dhcp_failing(client, stdout='Access is denied.', returncode=1)
    assert res.status_code == 403
    assert res.get_json()['adminRequired'] is True


def test_unrelated_failure_is_not_mislabelled_as_admin(client):
    """'access' alone used to trigger the admin label and mislead diagnosis."""
    res = post_dhcp_failing(client, stderr='Cannot access the network path.',
                            returncode=1)
    assert res.status_code == 500
    assert res.get_json()['adminRequired'] is False


def test_dhcp_already_enabled_does_not_skip_the_cleanup(client):
    """[BENCH 2026-07-28] netsh reports "already enabled" off the same interface
    flag a disconnected adapter always sets, so it declares success and removes
    nothing. Observed on the rig: the route returned 200 while the static
    192.168.50.20 was still assigned with PrefixOrigin Manual. The message must
    not short-circuit the removal of manually-assigned addresses.
    """
    calls = []
    fake = fake_shell(calls, netsh=FakeCompleted(
        stdout='DHCP is already enabled on this interface.', returncode=1))
    with patch('app.routes.subprocess.run', side_effect=fake):
        res = client.post('/api/network/dhcp', json={'adapter': 'Wi-Fi'})

    assert res.status_code == 200
    cleanup = [c for c in calls
               if c['argv'][0] != 'netsh' and 'Remove-NetIPAddress' in c['argv'][-1]]
    assert cleanup, 'netsh saying "already enabled" must not skip the cleanup'
    assert "PrefixOrigin -ne 'Dhcp'" in cleanup[0]['argv'][-1]
    assert cleanup[0]['kwargs']['env']['FIVE12_ADAPTER'] == 'Wi-Fi'


def test_dhcp_reports_a_static_address_it_could_not_remove(client):
    """The cleanup verifies rather than assumes; a survivor is a failure."""
    calls = []

    def _run(argv, **kwargs):
        argv = list(argv)
        calls.append({'argv': argv, 'kwargs': kwargs})
        if argv[0] == 'netsh':
            return FakeCompleted()
        if 'Remove-NetIPAddress' in argv[-1]:
            return FakeCompleted(
                stderr='Switched to DHCP but the static address 192.168.50.20 '
                       'could not be removed.', returncode=1)
        return FakeCompleted(stdout=json.dumps(ADAPTERS))

    with patch('app.routes.subprocess.run', side_effect=_run):
        res = client.post('/api/network/dhcp', json={'adapter': 'Wi-Fi'})

    assert res.status_code == 500
    assert '192.168.50.20' in res.get_json()['error']


def test_dhcp_cleanup_carries_no_operator_text_into_the_script(
        client, shell_hostile_inventory):
    """The cleanup is PowerShell again, so the transport rule still applies."""
    res = client.post('/api/network/dhcp', json={'adapter': INJECTION})
    assert res.status_code == 200
    cleanup = [c for c in shell_hostile_inventory
               if c['argv'][0] != 'netsh'
               and 'Remove-NetIPAddress' in c['argv'][-1]][0]
    assert INJECTION not in cleanup['argv'][-1]
    assert 'Start-Process' not in cleanup['argv'][-1]
    assert cleanup['kwargs']['env']['FIVE12_ADAPTER'] == INJECTION


def test_apply_failure_also_carries_detail(client):
    calls = []
    fake = fake_shell(calls, netsh=FakeCompleted(returncode=2))
    with patch('app.routes.subprocess.run', side_effect=fake):
        res = client.post('/api/network/apply',
                          json={'adapter': 'Ethernet 2', 'ip': '192.168.1.50'})
    assert res.status_code == 500
    assert 'exited 2' in res.get_json()['error']
