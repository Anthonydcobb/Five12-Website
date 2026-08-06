"""Parse a saved NETGEAR M4250 AV UI Overview page.

Pure: no network, no database, no Flask. Given the rendered HTML of the
Configure -> Overview page, returns a dict shaped for NetworkDevice.vendor_data.

Read-only by construction. The AV UI is a Vue SPA, so this must be fed the
RENDERED DOM (document.documentElement.outerHTML) -- a view-source of the shell
contains none of the data.

Design note: every field is independently optional. A NETGEAR firmware update
that renames one element must cost that one field, never the whole import, and
never a wrong value. A field that cannot be located is simply absent from the
returned dict.
"""
import re

from bs4 import BeautifulSoup

# lxml is not installed and needs a compiler on Windows. The stdlib backend is
# sufficient: this document is well-formed output from a Vue renderer.
_PARSER = 'html.parser'


def _text(node) -> str | None:
    """Visible text of `node`, or None when it has none.

    The AV UI nests icon <i> elements inside value divs (the edit pencils next
    to system name and management IP). Those are empty, so a plain get_text
    with whitespace stripped yields the value alone.
    """
    if node is None:
        return None
    txt = node.get_text(strip=True)
    return txt or None


def _by_id(soup, element_id: str) -> str | None:
    return _text(soup.find(id=element_id))


def _int_in(text: str | None) -> int | None:
    """First integer in `text`. Temperatures render as '25 ℃'."""
    if not text:
        return None
    m = re.search(r'-?\d+', text)
    return int(m.group()) if m else None


def _progress_value(soup, element_id: str) -> float | None:
    """A circular progress widget's value.

    Read from aria-valuenow rather than the rendered text: the attribute is the
    unformatted number, while the text carries a '%' that would need stripping.
    """
    node = soup.find(id=element_id)
    if node is None:
        return None
    try:
        return float(node.get('aria-valuenow'))
    except (TypeError, ValueError):
        return None


def _fan_mode(soup) -> str | None:
    """Label of the selected fan-mode radio ('Off' / 'Quiet' / 'Cool').

    The value lives on the checked <input> as an opaque code (1/2/3); the label
    beside it is the operator-facing word. Take the label so no code table has
    to be invented and kept in sync.
    """
    group = soup.find(id='fan_mode')
    if group is None:
        return None
    checked = group.select_one('.el-radio.is-checked .el-radio__label')
    return _text(checked)


# id -> output key, for the fields that are a plain text read.
_SIMPLE_FIELDS = {
    'device_serial': 'serial',
    'device_mac': 'baseMac',
    'device_model': 'model',
    'device_firmware': 'firmware',
    'device_bootver': 'bootVersion',
    'device_avuiversion': 'avUiVersion',
    'device_uptime': 'uptime',
    'device_manageip': 'managementIp',
    'device_serviceportip': 'oobIp',
    'device_stp': 'stpMode',
    'product_name': 'productName',
    'device_time': 'deviceTime',
}


def _parse_device(soup) -> dict:
    out = {}
    for element_id, key in _SIMPLE_FIELDS.items():
        val = _by_id(soup, element_id)
        if val is not None:
            out[key] = val

    # System name sits in its own span so the edit pencil stays out of it.
    name = soup.select_one('#device_name .item-name')
    if name is not None and _text(name):
        out['systemName'] = _text(name)

    temp = _int_in(_by_id(soup, 'fan_temp'))
    if temp is not None:
        out['tempC'] = temp
    max_temp = _int_in(_by_id(soup, 'max_temp'))
    if max_temp is not None:
        out['maxTempC'] = max_temp

    cpu = _progress_value(soup, 'cpu_monitor')
    if cpu is not None:
        out['cpuPercent'] = cpu
    mem = _progress_value(soup, 'memory_monitor')
    if mem is not None:
        out['memoryPercent'] = mem

    fan = _fan_mode(soup)
    if fan is not None:
        out['fanMode'] = fan
    return out


def parse_snapshot(html: str) -> dict:
    """Device details, profiles and per-port state from an Overview page.

    Returns {} for input that is not such a page. Never raises on malformed
    input -- it is fed operator-pasted text from hardware whose firmware can
    change under us, the same defensive posture read_port_status takes.
    """
    soup = BeautifulSoup(html or '', _PARSER)
    return _parse_device(soup)
