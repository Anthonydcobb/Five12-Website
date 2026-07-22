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
