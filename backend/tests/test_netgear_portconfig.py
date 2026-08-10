"""Port Configuration page parser tests.

Run against the real capture, never a synthetic fixture.

[VERIFIED 2026-08-10] The page's table is a `vue-recycle-scroller`, so a saved
page contains ONLY the rows rendered at capture time. This fixture is a
12-port switch and holds 10 rows; ports 11 and 12 are absent from the file.
The 10 below is therefore the CORRECT expected value, not a parser bug.
"""
from pathlib import Path

import pytest

from app.vendors.netgear_snapshot import (detect_page_type, parse_portconfig,
                                          parse_portconfig_identity)

FIXTURES = Path(__file__).parent / 'fixtures'
PORTCONFIG = FIXTURES / 'netgear_m4250_portconfig.html'
OVERVIEW = FIXTURES / 'netgear_m4250_overview.html'


@pytest.fixture
def portconfig_html():
    return PORTCONFIG.read_text(encoding='utf-8')


def test_detects_the_portconfig_page(portconfig_html):
    assert detect_page_type(portconfig_html) == 'portconfig'


def test_detects_the_overview_page():
    assert detect_page_type(OVERVIEW.read_text(encoding='utf-8')) == 'overview'


def test_returns_none_for_anything_else():
    assert detect_page_type('<html><body>hello</body></html>') is None
    assert detect_page_type('') is None
    assert detect_page_type(None) is None


def test_parses_only_the_rows_that_were_captured(portconfig_html):
    # Ten of twelve. See the module docstring -- this is the virtual scroller,
    # and pinning it here stops a future reader "fixing" it.
    rows = parse_portconfig(portconfig_html)
    assert len(rows) == 10
    assert [r['port'] for r in rows] == list(range(1, 11))


def test_reads_profile_and_template_from_the_row(portconfig_html):
    rows = {r['port']: r for r in parse_portconfig(portconfig_html)}
    assert rows[3]['profile'] == 'HogNet'
    assert rows[3]['template'] == 'Data'
    assert rows[1]['profile'] == 'Default'
    assert rows[1]['template'] == 'Default'


def test_reads_link_state_for_cross_checking(portconfig_html):
    rows = {r['port']: r for r in parse_portconfig(portconfig_html)}
    assert rows[1]['linkUp'] is True
    assert rows[2]['linkUp'] is False


def test_never_raises_on_junk():
    assert parse_portconfig('') == []
    assert parse_portconfig(None) == []
    assert parse_portconfig('<div class="port-configuration-row"></div>') == []


# The page names itself in #unit_model as "<model> ( <display name> )". That is
# NOT the identifier -- the display name is operator-editable and not
# guaranteed unique -- but it is an independent witness to which switch the
# operator meant, which is the one thing the explicit-MAC design cannot check.

def test_reads_the_model_and_name_the_page_claims(portconfig_html):
    ident = parse_portconfig_identity(portconfig_html)
    assert ident['systemName'] == 'FMB Switch 73'
    assert ident['model'] == 'M4250-10G2F-PoE+'


def test_identity_is_empty_when_the_page_does_not_say(portconfig_html):
    assert parse_portconfig_identity('') == {}
    assert parse_portconfig_identity(None) == {}
    assert parse_portconfig_identity('<div id="unit_model">no parens here</div>') == {}
