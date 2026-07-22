"""Pure logic for the smart patch-sheet importer: header detection, column
alias matching, mapping and address derivation. No Flask/DB dependencies."""
import math
import re
from io import BytesIO

CANONICAL_FIELDS = [
    "set", "fixture", "universe", "address", "endAddress", "type",
    "channelCount", "location", "wattage", "weight", "firmware", "notes",
]
INT_FIELDS = {"universe", "address", "endAddress", "channelCount"}
STR_FIELDS = {"set", "fixture", "type", "location", "wattage", "weight",
              "firmware", "notes"}

# Aliases are stored already-normalized (see normalize_header).
ALIASES = {
    "set":          {"set", "group", "sys", "system"},
    "fixture":      {"fix", "fix no", "fixture no", "fixture number", "unit",
                     "unit no", "chan no", "channel no"},
    "universe":     {"universe", "uni", "u", "net"},
    "address":      {"address", "addr", "add", "dmx", "dmx address",
                     "dmx addr", "start", "start address", "patch"},
    "endAddress":   {"end", "end add", "end addr", "end address", "last",
                     "last address", "thru"},
    "type":         {"type", "fixture type", "fixture", "model", "instrument",
                     "instrument type", "gear"},
    "channelCount": {"ch count", "ch cnt", "channel count", "channels",
                     "chans", "ch", "footprint", "dmx footprint", "slots"},
    "location":     {"location", "loc", "position", "pos", "area", "zone",
                     "spot"},
    "wattage":      {"wattage", "watt", "watts", "power", "w"},
    "weight":       {"weight", "wt", "mass", "lbs", "lb", "kg"},
    "firmware":     {"firmware", "fw", "version", "ver"},
    "notes":        {"notes", "note", "comment", "comments", "remark",
                     "remarks", "desc", "description"},
}
_ALL_ALIASES = {a for aliases in ALIASES.values() for a in aliases}


def normalize_header(value) -> str:
    if value is None:
        return ""
    s = str(value).strip().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)   # punctuation -> space
    return re.sub(r"\s+", " ", s).strip()


def guess_field(header):
    norm = normalize_header(header)
    if not norm:
        return None
    for field in CANONICAL_FIELDS:          # deterministic order
        if norm in ALIASES[field]:
            return field
    return None


def guess_mapping(headers):
    return {h: guess_field(h) for h in headers}


def detect_header_row(grid, scan_limit=15):
    """Return the index of the row whose cells best match known column
    aliases. Ties break to the earliest row; fallback is row 0."""
    best_idx, best_score = 0, 0
    for idx, row in enumerate(grid[:scan_limit]):
        score = sum(1 for cell in row if normalize_header(cell) in _ALL_ALIASES)
        if score > best_score:
            best_score, best_idx = score, idx
    return best_idx


def parse_int(value):
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.lower() == "nan":
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def clean_str(value):
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            value = int(value)
    s = str(value).strip()
    return s or None


def derive_row(row):
    out = {}
    for k in INT_FIELDS:
        out[k] = parse_int(row.get(k))
    for k in STR_FIELDS:
        out[k] = clean_str(row.get(k))
    a, e, c = out.get("address"), out.get("endAddress"), out.get("channelCount")
    if a is not None:
        if e is None and c is not None:
            out["endAddress"] = a + c - 1
        elif c is None and e is not None:
            out["channelCount"] = e - a + 1
    return out


def _row_is_blank(canonical):
    return all(canonical.get(f) in (None, "") for f in CANONICAL_FIELDS)


def apply_mapping(headers, data_rows, mapping):
    results = []
    for cells in data_rows:
        raw = {}
        for idx, header in enumerate(headers):
            field = mapping.get(header)
            if not field or field == "ignore":
                continue
            raw[field] = cells[idx] if idx < len(cells) else None
        canonical = derive_row(raw)
        if _row_is_blank(canonical):
            continue
        results.append(canonical)
    return results
