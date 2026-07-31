"""Pure logic for the smart patch-sheet importer: header detection, column
alias matching, mapping and address derivation. No Flask/DB dependencies."""
import json
import math
import re
from difflib import SequenceMatcher
from io import BytesIO
import pandas as pd

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
        number = float(s)
        if not math.isfinite(number) or not number.is_integer():
            return None
        return int(number)
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
        if (
            k == "channelCount"
            and clean_str(row.get(k)) is not None
            and out[k] is None
        ):
            raise ValueError("Channel count must be a whole number")
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


def _normalize_fixture_text(value) -> str:
    """Normalize punctuation and compact model tokens for fixture matching."""
    normalized = normalize_header(value)
    normalized = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_fixture_identity(value) -> str:
    """Case/space-normalize identity without discarding punctuation."""
    text = str(value or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def fixture_source_key(source_type, channel_count) -> str:
    """Stable key shared by preview and commit for one imported profile shape."""
    footprint = parse_int(channel_count)
    return json.dumps(
        [_normalize_fixture_identity(source_type), footprint],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def group_fixture_sources(rows) -> list[dict]:
    """Group repeated imported rows so the operator makes one profile choice."""
    grouped = {}
    for row in rows:
        source_type = clean_str(row.get("type"))
        if not source_type:
            continue
        channel_count = parse_int(row.get("channelCount"))
        key = fixture_source_key(source_type, channel_count)
        if key not in grouped:
            grouped[key] = {
                "key": key,
                "sourceType": source_type,
                "channelCount": channel_count,
                "rowCount": 0,
            }
        grouped[key]["rowCount"] += 1
    return list(grouped.values())


def _candidate_dict(candidate) -> dict:
    if isinstance(candidate, dict):
        return dict(candidate)
    return {
        "id": candidate.id,
        "manufacturer": candidate.manufacturer,
        "fixture": candidate.fixture,
        "channelCount": candidate.channel_count,
    }


def rank_fixture_candidates(source_type, channel_count, candidates, limit=5) -> list[dict]:
    """Rank fixture names only after enforcing footprint compatibility.

    Mode is embedded in Hog profile names, so token overlap carries mode/model
    numbers into the score. Similarity never overrides a supplied footprint.
    """
    source = _normalize_fixture_text(source_type)
    source_identity = _normalize_fixture_identity(source_type)
    if not source:
        return []
    source_tokens = set(source.split())
    footprint = parse_int(channel_count)
    ranked = []
    for candidate in candidates:
        item = _candidate_dict(candidate)
        candidate_count = parse_int(item.get("channelCount"))
        if footprint is not None and candidate_count != footprint:
            continue
        name = _normalize_fixture_text(item.get("fixture"))
        manufacturer = _normalize_fixture_text(item.get("manufacturer"))
        full_name = " ".join(piece for piece in (manufacturer, name) if piece)
        candidate_fixture = item.get("fixture") or ""
        candidate_manufacturer = item.get("manufacturer") or ""
        exact = source_identity in {
            _normalize_fixture_identity(candidate_fixture),
            _normalize_fixture_identity(
                f"{candidate_manufacturer} {candidate_fixture}"
            ),
            _normalize_fixture_identity(
                f"{candidate_manufacturer} — {candidate_fixture}"
            ),
        }
        candidate_tokens = set(full_name.split())
        union = source_tokens | candidate_tokens
        token_score = len(source_tokens & candidate_tokens) / len(union) if union else 0.0
        sequence_score = max(
            SequenceMatcher(None, source, name).ratio(),
            SequenceMatcher(None, source, full_name).ratio(),
        )
        score = 1.0 if exact else (0.6 * sequence_score + 0.4 * token_score)
        item.update({"exact": exact, "score": round(score, 4)})
        ranked.append(item)
    ranked.sort(key=lambda item: (-int(item["exact"]), -item["score"], item.get("id", 0)))
    return ranked[:limit]


def read_table(data, filename):
    name = (filename or "").lower()
    bio = BytesIO(data)
    if name.endswith(".csv"):
        df = pd.read_csv(bio, header=None, dtype=object,
                         na_values=[""], keep_default_na=True)
    else:
        df = pd.read_excel(bio, header=None, dtype=object, engine="openpyxl")
    df = df.where(pd.notnull(df), None)
    return df.values.tolist()
