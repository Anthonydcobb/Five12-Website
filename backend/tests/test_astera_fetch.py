"""Astera adapter — the hardened HTTP boundary (review B4/B5).

Beyond require_private_host (shared, resolved-IP-in-URL), the Astera client
additionally must: refuse redirects, cap the response size, require a JSON
content type, bracket IPv6 literals, and refuse IPv6 link-local until zone
handling is deliberately designed. Every test runs against a fake transport;
no packet leaves the machine.
"""

import pytest

from app.integrations import astera
from app.integrations.astera import AsteraAdapter, MAX_RESPONSE_BYTES


class FakeResponse:
    def __init__(self, status=200, ctype='application/json', body=b'{"ok": 1}'):
        self.status_code = status
        self.headers = {'Content-Type': ctype}
        self._body = body

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        pass


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setenv('FIVE12_ASTERA_TOOLS', '1')
    monkeypatch.setenv('FIVE12_ASTERA_HOST', 'astera-phone.local')
    monkeypatch.setattr(astera, 'require_private_host', lambda h: '192.168.1.50')
    return AsteraAdapter(sim=False)


@pytest.fixture
def transport(monkeypatch):
    """Capture the request; queue the response."""
    seen = {}

    def install(response):
        def fake_get(url, **kwargs):
            seen['url'] = url
            seen['kwargs'] = kwargs
            return response
        monkeypatch.setattr(astera.requests, 'get', fake_get)
        return seen
    return install


def test_fetch_builds_url_from_resolved_ip_and_refuses_redirects(adapter, transport):
    seen = transport(FakeResponse())
    adapter._fetch_json('status')
    assert seen['url'] == 'http://192.168.1.50:8080/api/status'
    assert seen['kwargs']['allow_redirects'] is False
    assert seen['kwargs']['stream'] is True
    assert seen['kwargs']['timeout'] <= 5


def test_fetch_rejects_a_redirect_response(adapter, transport):
    transport(FakeResponse(status=302))
    with pytest.raises(ValueError, match='redirect'):
        adapter._fetch_json('status')


def test_fetch_rejects_non_json_content_type(adapter, transport):
    transport(FakeResponse(ctype='text/html', body=b'<html>'))
    with pytest.raises(ValueError, match='content type'):
        adapter._fetch_json('status')


def test_fetch_accepts_json_with_charset_parameter(adapter, transport):
    transport(FakeResponse(ctype='application/json; charset=utf-8'))
    assert adapter._fetch_json('status') == {'ok': 1}


def test_fetch_caps_the_response_size(adapter, transport):
    transport(FakeResponse(body=b'x' * (MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(ValueError, match='large'):
        adapter._fetch_json('status')


def test_fetch_rejects_http_error_status(adapter, transport):
    transport(FakeResponse(status=500))
    with pytest.raises(ValueError, match='500'):
        adapter._fetch_json('status')


def test_fetch_brackets_an_ipv6_literal(adapter, transport, monkeypatch):
    monkeypatch.setattr(astera, 'require_private_host', lambda h: 'fd12::5')
    seen = transport(FakeResponse())
    adapter._fetch_json('targets')
    assert seen['url'] == 'http://[fd12::5]:8080/api/targets'


def test_fetch_refuses_ipv6_link_local(adapter, transport, monkeypatch):
    monkeypatch.setattr(astera, 'require_private_host', lambda h: 'fe80::1')
    transport(FakeResponse())
    with pytest.raises(ValueError, match='link-local'):
        adapter._fetch_json('status')


def test_fetch_only_accepts_allowlisted_endpoint_keys(adapter, transport):
    """The path argument is a key into ENDPOINTS, never a path — there is no
    way to reach /api/launch or any other state-changing route."""
    transport(FakeResponse())
    with pytest.raises(KeyError):
        adapter._fetch_json('launch')
