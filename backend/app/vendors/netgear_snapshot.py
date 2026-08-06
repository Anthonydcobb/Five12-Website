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


def _rgb_to_hex(style: str | None) -> str | None:
    """'background-color: rgb(0, 255, 0);' -> '#00ff00'.

    The profile swatch colour is worth carrying: it is how an operator
    recognises FixtureNet at a glance on the switch's own page, and reusing it
    avoids inventing a second palette for the same four networks.
    """
    if not style:
        return None
    m = re.search(r'rgba?\(\s*(\d+)\D+(\d+)\D+(\d+)', style)
    if not m:
        return None
    return '#%02x%02x%02x' % tuple(int(g) for g in m.groups())


def _parse_profiles(soup) -> list:
    """Rows of the Configured Profiles table.

    Parsed positionally, NOT by id. The AV UI puts id="profile_name" and
    id="profile_color" on EVERY row, so soup.find(id=...) returns the first row
    only -- which imports 'Default' and silently drops the four profiles an
    operator actually cares about.

    Element Plus renders the header and the body as two separate <table>s; only
    the body carries data rows.
    """
    table = soup.select_one('#configured_profiles_table table.el-table__body')
    if table is None:
        return []
    out = []
    for row in table.select('tbody tr'):
        cells = row.find_all('td')
        if len(cells) < 5:
            continue
        name = _text(cells[0].select_one(
            'span[id="profile_name"], span[id="profile_defaultName"]'))
        if name is None:
            # Fall back to the cell's own text, so a renamed id costs the
            # swatch colour rather than the whole row.
            name = _text(cells[0])
        if not name:
            continue
        ip = _text(cells[3])
        swatch = cells[0].select_one('.color-block')
        out.append({
            'name': name,
            'template': _text(cells[1]),
            'vlan': _int_in(_text(cells[2])),
            # 'N/A' is the AV UI's own way of saying the profile has no
            # management IP. Carrying it through as a string would render a
            # literal "N/A" in a column of real addresses.
            'ip': None if ip in (None, 'N/A') else ip,
            'portCount': _int_in(_text(cells[4])),
            'color': _rgb_to_hex(swatch.get('style') if swatch else None),
        })
    return out


# Link-up is marked by 'lan-connected' OR 'lan-connected-powered' -- the latter
# is a PoE port that is both linked and delivering power, and it is a DISTINCT
# class, not 'lan-connected' with a suffix. [VERIFIED 2026-08-06] against FMB
# Switch 73 port 5, up at 100T Full delivering 6W to a Raspberry Pi.
#
# Testing membership of 'lan-connected' alone reports that port DOWN. Testing
# by substring instead would be right by accident, and would also swallow any
# future 'lan-connected-*' class whose meaning we have not seen. Match the two
# known classes explicitly, so an unknown third shows up as down and gets
# noticed rather than silently absorbed.
_LINK_UP_CLASSES = {'lan-connected', 'lan-connected-powered'}


def _parse_ports(soup) -> list:
    """Per-port state read from the port graphic.

    Each port element carries its own number in .lan-font, so this mapping is
    structural -- unlike the popovers in _merge_popovers, which are position-
    dependent and therefore guarded.

    Fibre ports nest .lan-font inside .fib-view; copper ports put it in
    .lan-three. Searching for the class rather than the container covers both.
    """
    out = []
    for lan in soup.select('.sakura-port-lan'):
        number = _int_in(_text(lan.select_one('.lan-font')))
        if number is None:
            continue
        content = lan.select_one('.lan-content')
        classes = content.get('class', []) if content else []
        swatch = lan.select_one('.lan-three') or lan.select_one('.fib-view')
        trunk = None
        if lan.select_one('.port-manualTrunk'):
            trunk = 'manual'
        elif lan.select_one('.port-autoTrunk'):
            trunk = 'auto'
        out.append({
            'port': number,
            'media': 'fiber' if lan.select_one('.fib-view') else 'copper',
            'linkUp': bool(_LINK_UP_CLASSES & set(classes)),
            'poe': lan.select_one('.port-poe') is not None,
            'trunk': trunk,
            'color': _rgb_to_hex(swatch.get('style') if swatch else None),
        })
    out.sort(key=lambda p: p['port'])
    return out


# Popover row label -> output key. Labels render as 'IP Address :'.
_POPOVER_FIELDS = {
    'Host': 'host',
    'MAC Address': 'mac',
    'IP Address': 'ip',
    'LLDP Remote ID': 'lldpRemoteId',
    'Port Type': 'portType',
    'Link Speed': 'linkSpeed',
    'Power Usage': 'powerWatts',
    'Profile Name': 'profile',
    'Profile Template': 'template',
}


def _parse_popover(node) -> dict:
    """One port popover, keyed by its own row labels rather than by position.

    Row order within a popover varies with how much the switch knows about the
    attached device, so labels are the only stable key here.
    """
    out = {}
    for item in node.select('.port-item'):
        label = _text(item.select_one('.item-label'))
        if not label:
            continue
        label = label.rstrip(':').strip()
        value = _text(item.select_one('.flex-item'))
        if value is None:
            continue
        if label == 'VLAN ID':
            vlans = [int(v) for v in re.findall(r'\d+', value)]
            if vlans:
                out['vlans'] = vlans
        elif label in _POPOVER_FIELDS:
            out[_POPOVER_FIELDS[label]] = value
    return out


def _merge_popovers(soup, ports: list) -> bool:
    """Fold popover fields into `ports`, or refuse to and say so.

    Returns True when the merge happened, False when it was declined.

    The ONLY thing associating a popover with a port is document order --
    popovers live in a detached container at the end of the body, not inside
    the ports they describe. So the association is accepted only when the two
    counts match exactly AND the ports are in ascending order. On any mismatch
    every popover-sourced field is dropped, and the caller surfaces that; the
    structurally-read fields from _parse_ports are unaffected because they
    never depended on ordering.

    Attributing one port's connected fixture to its neighbour is the failure
    this exists to prevent: it is silent, plausible, and gets acted on.

    Child popovers (.sakura-child-port-popover) are stack-member panels
    carrying no port data; they are interleaved with the real ones and are
    excluded by the class selector.
    """
    popovers = soup.select('.sakura-port-popover')
    if not popovers or len(popovers) != len(ports):
        return False
    if [p['port'] for p in ports] != sorted(p['port'] for p in ports):
        return False
    for port, node in zip(ports, popovers):
        port.update(_parse_popover(node))
    return True


def parse_snapshot(html: str) -> dict:
    """Device details, profiles and per-port state from an Overview page.

    Returns {} for input that is not such a page. Never raises on malformed
    input -- it is fed operator-pasted text from hardware whose firmware can
    change under us, the same defensive posture read_port_status takes.
    """
    # Not just falsy input: the import route hands us whatever JSON supplied,
    # so a non-str (dict, list, int) is reachable from outside and would raise
    # inside BeautifulSoup. Returning {} makes the route refuse it as an
    # unrecognised page rather than 500.
    if not isinstance(html, str) or not html:
        return {}
    soup = BeautifulSoup(html, _PARSER)
    data = _parse_device(soup)
    data['profiles'] = _parse_profiles(soup)
    ports = _parse_ports(soup)
    data['netgearPorts'] = ports
    if ports:
        data['portCount'] = len(ports)
        data['activePorts'] = sum(1 for p in ports if p['linkUp'])
        data['netgearPortHostsAvailable'] = _merge_popovers(soup, ports)
    return data
