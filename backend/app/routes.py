# File: backend/app/routes.py
import os
import subprocess
import json
import ipaddress
import re
import socket
import struct
import time
import requests as req
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, request, jsonify, current_app, send_file, send_from_directory
from .models import Show, PatchSheet, Fixture, PatchRow, LabelTemplate
from . import db
from .fixture_library import FixtureLibraryBusyError, fixture_catalog_mutation_lock
from .patch_import import (
    read_table, detect_header_row, guess_mapping, apply_mapping,
    fixture_source_key, group_fixture_sources, rank_fixture_candidates,
)
import pandas as pd
from io import BytesIO
from openpyxl import Workbook

# Directory containing the built React app (set by run_desktop.py)
_STATIC_DIR = os.environ.get('FIVE12_STATIC_DIR', '')


bp = Blueprint('api', __name__)

def to_int(val):
    if pd.isna(val):
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    val = re.sub(r'\D', '', str(val))  # Remove non-digit chars like "w"
    return int(val) if val else 0

# ───────────── SHOWS ───────────── #

@bp.route('/api/shows', methods=['GET'])
def list_shows():
    shows = Show.query.all()
    return jsonify([s.to_dict() for s in shows])

@bp.route('/api/shows', methods=['POST'])
def create_show():
    try:
        data = request.get_json(force=True)
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'error': 'Name is required'}), 400
        if Show.query.filter_by(name=name).first():
            return jsonify({'error': 'Show already exists'}), 409
        new_show = Show(name=name)
        db.session.add(new_show)
        db.session.commit()
        return jsonify(new_show.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Failed to create show")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/shows/<int:show_id>', methods=['GET'])
def get_show(show_id):
    show = Show.query.get_or_404(show_id)
    return jsonify(show.to_dict())

# ───────────── PATCH SHEETS ───────────── #

@bp.route('/api/shows/<int:show_id>/patch-sheets', methods=['GET'])
def list_show_patch_sheets(show_id):
    show = Show.query.get_or_404(show_id)
    return jsonify([p.to_dict() for p in show.patches])

@bp.route('/api/shows/<int:show_id>/patch-sheets', methods=['POST'])
def create_patch_sheet(show_id):
    try:
        Show.query.get_or_404(show_id)
        data = request.get_json(force=True)
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'error': 'Name is required'}), 400
        new_patch = PatchSheet(name=name, show_id=show_id)
        db.session.add(new_patch)
        db.session.commit()
        return jsonify(new_patch.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Failed to create patch sheet")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/shows/<int:show_id>', methods=['DELETE'])
def delete_show(show_id):
    show = Show.query.get_or_404(show_id)
    for patch in show.patches:
        PatchRow.query.filter_by(patch_id=patch.id).delete()
    db.session.delete(show)
    db.session.commit()
    return '', 204

@bp.route('/api/shows/<int:show_id>/patch-sheets/<int:patch_id>', methods=['GET'])
def get_patch_sheet(show_id, patch_id):
    Show.query.get_or_404(show_id)
    patch = PatchSheet.query.get_or_404(patch_id)
    return jsonify(patch.to_dict())

@bp.route('/api/patch-sheets/<int:patch_id>', methods=['DELETE'])
def delete_patch_sheet(patch_id):
    patch = PatchSheet.query.get_or_404(patch_id)
    PatchRow.query.filter_by(patch_id=patch_id).delete()
    db.session.delete(patch)
    db.session.commit()
    return '', 204

# ───────────── PATCH ROWS ───────────── #

def _patch_address_error(row):
    values = (row.universe, row.address, row.end_address)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        return 'Universe, address, and end address must be set together'
    try:
        universe, address, end_address = map(int, values)
    except (TypeError, ValueError):
        return 'Universe and addresses must be integers'
    if universe < 1:
        return 'Universe must be 1 or greater'
    if not 1 <= address <= 512 or not 1 <= end_address <= 512:
        return 'DMX addresses must stay between 1 and 512'
    if end_address < address:
        return 'End address cannot be before start address'
    return None

@bp.route('/api/patch-sheets/<int:patch_id>/rows', methods=['GET'])
def list_rows_for_patch(patch_id):
    PatchSheet.query.get_or_404(patch_id)
    rows = (
        PatchRow.query
        .filter_by(patch_id=patch_id)
        .order_by(PatchRow.set_name)
        .all()
    )
    return jsonify([r.to_dict() for r in rows])

@bp.route('/api/patch-sheets/<int:patch_id>/rows', methods=['POST'])
def create_patch_row(patch_id):
    try:
        PatchSheet.query.get_or_404(patch_id)
        data = request.get_json(force=True)
        r = PatchRow(
            patch_id=patch_id,
            set_name=data.get('set'),
            fixture=data.get('fixture'),
            universe=data.get('universe'),
            address=data.get('address'),
            end_address=data.get('endAddress'),
            type=data.get('type'),
            channel_count=data.get('channelCount'),
            location=data.get('location'),
            wattage=data.get('wattage'),
            weight=data.get('weight'),
            notes=data.get('notes'),
            firmware=data.get('firmware'),
        )
        if error := _patch_address_error(r):
            return jsonify({'error': error}), 400
        db.session.add(r)
        db.session.commit()
        return jsonify(r.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Failed to create patch row")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/patch-sheets/rows/<int:row_id>', methods=['PUT'])
def update_patch_row(row_id):
    try:
        r = PatchRow.query.get_or_404(row_id)
        data = request.get_json(force=True)
        mapping = {
            'set': 'set_name',
            'fixture': 'fixture',
            'universe': 'universe',
            'address': 'address',
            'endAddress': 'end_address',
            'type': 'type',
            'channelCount': 'channel_count',
            'location': 'location',
            'wattage': 'wattage',
            'weight': 'weight',
            'notes': 'notes',
            'firmware': 'firmware'
        }
        for field, attr in mapping.items():
            if field in data:
                setattr(r, attr, data[field])
        if error := _patch_address_error(r):
            db.session.rollback()
            return jsonify({'error': error}), 400
        db.session.commit()
        return jsonify(r.to_dict())
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Failed to update patch row {row_id}")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/patch-sheets/rows/<int:row_id>', methods=['DELETE'])
def delete_patch_row(row_id):
    r = PatchRow.query.get_or_404(row_id)
    db.session.delete(r)
    db.session.commit()
    return '', 204

# ───────────── FIXTURES ───────────── #

@bp.route('/api/fixtures', methods=['GET'])
def list_fixtures():
    fixtures = Fixture.query.order_by(Fixture.fixture).all()
    return jsonify([f.to_dict() for f in fixtures])

@bp.route('/api/fixtures', methods=['POST'])
def create_fixture():
    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            raise ValueError('Fixture payload must be an object')
        name = str(data.get('fixture') or '').strip()
        manufacturer = str(data.get('manufacturer') or '').strip() or None
        draft = data.get('draft') is True
        if draft:
            with fixture_catalog_mutation_lock():
                f = Fixture(
                    fixture='', notes='', channel_count=0,
                    wattage=0, weight=0, firmware='',
                )
                db.session.add(f)
                db.session.commit()
            return jsonify(f.to_dict()), 201
        if not name:
            raise ValueError('Fixture name is required')
        if len(name) > 120:
            raise ValueError('Fixture name exceeds 120 characters')
        if manufacturer and len(manufacturer) > 120:
            raise ValueError('Manufacturer exceeds 120 characters')
        raw_count = data.get('channelCount')
        if (
            isinstance(raw_count, bool)
            or isinstance(raw_count, float) and not raw_count.is_integer()
        ):
            raise ValueError('Channel count must be an integer')
        try:
            channel_count = int(raw_count)
        except (TypeError, ValueError) as exc:
            raise ValueError('Channel count must be an integer') from exc
        if not 1 <= channel_count <= 512:
            raise ValueError('Channel count must be between 1 and 512')

        with fixture_catalog_mutation_lock():
            duplicate_query = Fixture.query.filter(
                db.func.lower(Fixture.fixture) == name.lower(),
                Fixture.channel_count == channel_count,
            )
            if manufacturer:
                duplicate_query = duplicate_query.filter(
                    db.func.lower(Fixture.manufacturer) == manufacturer.lower()
                )
            else:
                duplicate_query = duplicate_query.filter(db.or_(
                    Fixture.manufacturer.is_(None), Fixture.manufacturer == ''
                ))
            duplicate = duplicate_query.first()
            if duplicate:
                return jsonify({
                    'error': 'That fixture profile already exists',
                    'existing': duplicate.to_dict(),
                }), 409

            f = Fixture(
                fixture=name,
                manufacturer=manufacturer,
                notes=str(data.get('notes') or '').strip(),
                channel_count=channel_count,
                wattage=data.get('wattage'),
                weight=data.get('weight'),
                firmware=str(data.get('firmware') or '').strip(),
            )
            db.session.add(f)
            db.session.commit()
        return jsonify(f.to_dict()), 201
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except FixtureLibraryBusyError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Failed to create fixture")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/fixtures/<int:id>', methods=['PUT'])
def update_fixture(id):
    try:
        data = request.get_json(force=True)
        with fixture_catalog_mutation_lock():
            f = Fixture.query.get_or_404(id)
            new_fixture = (data.get('fixture', f.fixture) or '').strip()
            new_channel_count = data.get('channelCount', f.channel_count)
            if f.library_source and (
                new_fixture != f.fixture or new_channel_count != f.channel_count
            ):
                # Once a vendor profile's identity/footprint is edited it is a
                # manual Five12 row, not an official Hog profile.
                f.manufacturer = None
                f.hog_uuid = None
                f.revision_id = None
                f.library_type = None
                f.library_origin = None
                f.library_source = None
                f.library_version = None
            f.fixture = new_fixture
            f.notes = (data.get('notes', f.notes) or '').strip()
            f.channel_count = new_channel_count
            f.wattage = data.get('wattage', f.wattage)
            f.weight = data.get('weight', f.weight)
            f.firmware = (data.get('firmware', f.firmware) or '').strip()
            db.session.commit()
        return jsonify(f.to_dict())
    except FixtureLibraryBusyError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Failed to update fixture")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/fixtures/<int:id>', methods=['DELETE'])
def delete_fixture(id):
    try:
        with fixture_catalog_mutation_lock():
            f = Fixture.query.get_or_404(id)
            db.session.delete(f)
            db.session.commit()
        return '', 204
    except FixtureLibraryBusyError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 409

# ───────────── ALL PATCH ROWS FOR SHOW ───────────── #

@bp.route('/api/shows/<int:show_id>/patch-sheets/all-rows')
def get_all_patch_rows(show_id):
    sheets = PatchSheet.query.filter_by(show_id=show_id).all()
    all_rows = []
    for sheet in sheets:
        for row in sheet.rows:
            all_rows.append({
                'patchSheetId': sheet.id,
                'patchSheetName': sheet.name,
                'fixture': row.fixture,
                'set': row.set_name,
                'location': row.location,
                'universe': row.universe,
                'address': row.address,
                'endAddress': row.end_address
            })
    return jsonify(all_rows)

# ───────────── EXCEL IMPORT ───────────── #

@bp.route('/api/patch-sheets/<int:patch_id>/import-excel', methods=['POST'])
def import_patch_sheet_excel(patch_id):
    try:
        if 'file' not in request.files:
            return {'error': 'No file uploaded'}, 400

        file = request.files['file']
        df = pd.read_excel(BytesIO(file.read()), engine='openpyxl', header=4)  # 👈 use 5th row
        print("Excel columns:", df.columns.tolist())

        # Fail early if headers still bad
        if all(col.startswith("Unnamed") for col in df.columns):
            return {'error': 'Excel import failed: column headers not detected. Try checking header row position.'}, 400

        column_map = {
            'Fix #': 'fixture',
            'Fix Type': 'type',
            'Uni': 'universe',
            'Add': 'address',
            'End Add': 'endAddress',
            'ch. Count': 'channelCount',
            'Location': 'location',
            'Weight': 'weight',
            'Wattage': 'wattage',
            'Notes': 'notes',
            'FW': 'firmware',
            'set': 'set'
        }
        df = df.rename(columns=column_map)
        print("Mapped columns:", df.columns.tolist())

        required = {'fixture', 'type', 'universe', 'address', 'endAddress', 'channelCount'}
        if not required.issubset(df.columns):
            missing = required - set(df.columns)
            return {'error': f'Missing columns: {missing}'}, 400

        inserted = 0
        for i, row in df.iterrows():
            row_data = row.where(pd.notnull(row), None).to_dict()  # 👈 replace NaN with None
            print(f"Inserting row {i}: {row_data}")
            new_row = PatchRow(
                patch_id=patch_id,
                fixture=row_data.get('fixture'),
                type=row_data.get('type'),
                channel_count=row_data.get('channelCount'),
                universe=row_data.get('universe'),
                address=row_data.get('address'),
                end_address=row_data.get('endAddress'),
                set_name=row_data.get('set'),
                location=row_data.get('location'),
                notes=row.get('notes', '').strip(),
                wattage=row_data.get('wattage'),
                weight=row_data.get('weight'),
                firmware=str(row.get('firmware') or '').strip(),
            )
            db.session.add(new_row)
            inserted += 1

        db.session.commit()
        return jsonify({'inserted': inserted})

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Excel import failed")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/patch-sheets/<int:patch_id>/import/analyze', methods=['POST'])
def analyze_patch_import(patch_id):
    try:
        if 'file' not in request.files:
            return {'error': 'No file uploaded'}, 400
        f = request.files['file']
        grid = read_table(f.read(), f.filename)
        if not grid:
            return {'error': 'The file appears to be empty.'}, 400
        hidx = detect_header_row(grid)
        headers = [('' if c is None else str(c)).strip() for c in grid[hidx]]
        named = [h for h in headers if h]
        data_rows = grid[hidx + 1:]
        mapping = guess_mapping(headers)
        preview = []
        for cells in data_rows[:5]:
            preview.append({
                headers[i]: (cells[i] if i < len(cells) else None)
                for i in range(len(headers)) if headers[i]
            })
        row_count = sum(
            1 for cells in data_rows
            if any(c not in (None, '') for c in cells)
        )
        return jsonify({
            'headerRowIndex': hidx,
            'theirColumns': named,
            'suggestedMapping': {h: mapping.get(h) for h in named},
            'previewRows': preview,
            'rowCount': row_count,
        })
    except Exception as e:
        current_app.logger.exception("Patch import analyze failed")
        return jsonify({'error': str(e)}), 500


def _canonical_patch_upload():
    """Parse the shared patch-import multipart fields into canonical rows."""
    if 'file' not in request.files:
        raise ValueError('No file uploaded')
    f = request.files['file']
    try:
        mapping = json.loads(request.form.get('mapping', '{}'))
    except json.JSONDecodeError as exc:
        raise ValueError('Invalid column mapping') from exc
    if not isinstance(mapping, dict):
        raise ValueError('Invalid column mapping')
    try:
        header_idx = int(request.form.get('headerRowIndex', 0))
    except ValueError as exc:
        raise ValueError('Invalid header row') from exc
    grid = read_table(f.read(), f.filename)
    if not grid:
        raise ValueError('The file appears to be empty.')
    if header_idx < 0 or header_idx >= len(grid):
        raise ValueError('Header row is outside the uploaded file')
    headers = [('' if c is None else str(c)).strip() for c in grid[header_idx]]
    data_rows = grid[header_idx + 1:]
    return apply_mapping(headers, data_rows, mapping), data_rows


def _fixture_match_payload(fixture):
    return {
        'id': fixture.id,
        'fixture': fixture.fixture,
        'displayName': (
            f'{fixture.manufacturer} — {fixture.fixture}'
            if fixture.manufacturer else fixture.fixture
        ),
        'manufacturer': fixture.manufacturer,
        'channelCount': fixture.channel_count,
    }


@bp.route('/api/patch-sheets/<int:patch_id>/import/matches', methods=['POST'])
def preview_patch_fixture_matches(patch_id):
    """Group imported fixture types and rank exact-footprint catalog profiles."""
    if db.session.get(PatchSheet, patch_id) is None:
        return jsonify({'error': 'Patch sheet not found'}), 404
    try:
        canonical_rows, _ = _canonical_patch_upload()
        groups = group_fixture_sources(canonical_rows)
        footprints = sorted({
            group['channelCount'] for group in groups
            if group['channelCount'] is not None
        })
        by_footprint = {}
        if footprints:
            candidates = Fixture.query.filter(
                Fixture.channel_count.in_(footprints),
                Fixture.channel_count.between(1, 512),
                db.or_(Fixture.library_type.is_(None), Fixture.library_type != 'part'),
            ).all()
            for fixture in candidates:
                by_footprint.setdefault(fixture.channel_count, []).append(fixture)

        response_groups = []
        for group in groups:
            ranked = rank_fixture_candidates(
                group['sourceType'], group['channelCount'],
                by_footprint.get(group['channelCount'], []),
            )
            suggestions = []
            for item in ranked:
                fixture = db.session.get(Fixture, item['id'])
                payload = _fixture_match_payload(fixture)
                payload.update({'exact': item['exact'], 'score': item['score']})
                suggestions.append(payload)
            exact_ids = [item['id'] for item in suggestions if item['exact']]
            response_groups.append({
                **group,
                'suggestions': suggestions,
                'selectedFixtureId': exact_ids[0] if len(exact_ids) == 1 else None,
            })
        return jsonify({'groups': response_groups})
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception('Patch fixture matching failed')
        return jsonify({'error': str(exc)}), 500


# Max lengths for PatchRow's bounded string columns (see backend/app/models.py).
# `notes` is TEXT (unbounded) and int fields (universe/address/end_address/
# channel_count) are excluded — only string columns can overflow.
_PATCHROW_MAXLEN = {
    'set': 50, 'fixture': 50, 'type': 120, 'location': 120,
    'wattage': 50, 'weight': 50, 'firmware': 120,
}


def _fit(value, maxlen):
    """Truncate a string value to fit a column's max length.

    A foreign sheet can have a value longer than our column width; rather
    than fail the whole import (MySQL strict mode) or silently corrupt data
    (SQLite), we truncate to make someone else's patch fit into ours.
    """
    if isinstance(value, str) and len(value) > maxlen:
        return value[:maxlen]
    return value


@bp.route('/api/patch-sheets/<int:patch_id>/import/commit', methods=['POST'])
def commit_patch_import(patch_id):
    try:
        if db.session.get(PatchSheet, patch_id) is None:
            return jsonify({'error': 'Patch sheet not found'}), 404
        canonical_rows, data_rows = _canonical_patch_upload()
        raw_selections = request.form.get('fixtureSelections')
        selections = json.loads(raw_selections) if raw_selections else {}
        if not isinstance(selections, dict):
            raise ValueError('Invalid fixture selections')

        selected_ids = set()
        for value in selections.values():
            if value is None:
                continue
            try:
                selected_ids.add(int(value))
            except (TypeError, ValueError) as exc:
                raise ValueError('Invalid selected fixture ID') from exc
        selected_fixtures = {
            fixture.id: fixture
            for fixture in Fixture.query.filter(Fixture.id.in_(selected_ids)).all()
        } if selected_ids else {}
        if len(selected_fixtures) != len(selected_ids):
            raise ValueError('A selected fixture profile no longer exists')

        prepared = []
        matched_rows = 0
        unmatched_rows = 0
        for source_row in canonical_rows:
            row = dict(source_row)
            source_type = row.get('type')
            key = fixture_source_key(source_type, row.get('channelCount'))
            selected_value = selections.get(key)
            if selected_value is not None:
                selected = selected_fixtures[int(selected_value)]
                if (
                    selected.library_type == 'part'
                    or not selected.channel_count
                    or not 1 <= selected.channel_count <= 512
                ):
                    raise ValueError(
                        f'Selected fixture {selected.fixture} is not patchable'
                    )
                imported_count = row.get('channelCount')
                if imported_count is not None and imported_count != selected.channel_count:
                    raise ValueError(
                        f'Imported footprint {imported_count} does not match '
                        f'selected fixture footprint {selected.channel_count}'
                    )
                row['type'] = selected.fixture
                row['channelCount'] = selected.channel_count
                if row.get('address') is not None:
                    row['endAddress'] = row['address'] + selected.channel_count - 1
                matched_rows += 1
            elif source_type:
                unmatched_rows += 1
            prepared.append(row)

        # Validate every selection before adding any row to the session. A bad
        # profile must not produce a partial import.
        for row in prepared:
            db.session.add(PatchRow(
                patch_id=patch_id,
                set_name=_fit(row.get('set'), _PATCHROW_MAXLEN['set']),
                fixture=_fit(row.get('fixture'), _PATCHROW_MAXLEN['fixture']),
                universe=row.get('universe'),
                address=row.get('address'),
                end_address=row.get('endAddress'),
                type=_fit(row.get('type'), _PATCHROW_MAXLEN['type']),
                channel_count=row.get('channelCount'),
                location=_fit(row.get('location'), _PATCHROW_MAXLEN['location']),
                wattage=_fit(row.get('wattage'), _PATCHROW_MAXLEN['wattage']),
                weight=_fit(row.get('weight'), _PATCHROW_MAXLEN['weight']),
                firmware=_fit(row.get('firmware'), _PATCHROW_MAXLEN['firmware']),
                notes=row.get('notes'),
            ))
        db.session.commit()
        non_blank = sum(1 for cells in data_rows
                        if any(c not in (None, '') for c in cells))
        inserted = len(prepared)
        return jsonify({
            'inserted': inserted,
            'skipped': max(0, non_blank - inserted),
            'matchedRows': matched_rows,
            'unmatchedRows': unmatched_rows,
        })
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Patch import commit failed")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/fixtures/import-excel', methods=['POST'])
def import_fixtures_excel():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        file = request.files['file']
        df = pd.read_excel(BytesIO(file.read()), engine='openpyxl', header=1)

        # Column renaming
        column_map = {
            'FIXTURE': 'fixture',
            'CH Count': 'channel_count',
            'Wattage': 'wattage',
            'Weight': 'weight',
            'FW': 'firmware',
            'Notes': 'notes'
        }
        df = df.rename(columns=column_map)
        df = df[list(column_map.values())]  # keep only expected columns
        df = df.dropna(how='all')  # drop completely blank rows

        from .models import Fixture

        with fixture_catalog_mutation_lock():
            existing = {f.fixture.lower(): f for f in Fixture.query.all()}
            duplicates = []
            inserted = 0

            for _, row in df.iterrows():
                name = str(row.get('fixture')).strip()
                if not name:
                    continue
                if name.lower() in existing:
                    duplicates.append({'existing': existing[name.lower()].to_dict(), 'new': row.to_dict()})
                    continue
                new = Fixture(
                    fixture=str(row.get('fixture') or '').strip(),
                    notes=str(row.get('notes') or '').strip(),
                    channel_count=to_int(row.get('channel_count')),
                    wattage=to_int(row.get('wattage')),
                    weight=to_int(row.get('weight')),
                    firmware=str(row.get('firmware') or '').strip()
                )

                db.session.add(new)
                inserted += 1

            db.session.commit()
        return jsonify({'inserted': inserted, 'duplicates': duplicates})

    except FixtureLibraryBusyError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Fixture import failed")
        return jsonify({'error': str(e)}), 500
    


@bp.route('/api/patch-sheets/<int:patch_id>/export-excel', methods=['GET'])
def export_patch_sheet_excel(patch_id):
    try:
        patch = PatchSheet.query.get_or_404(patch_id)
        rows = PatchRow.query.filter_by(patch_id=patch_id).all()

        wb = Workbook()
        ws = wb.active
        ws.title = patch.name or "Patch Sheet"

        # Header row
        headers = ['Set', 'Fix #', 'Uni', 'Add', 'End Add', 'Fix Type', 'ch. Count',
                   'Location', 'Wattage', 'Weight', 'Notes', 'FW']
        ws.append(headers)

        # Data rows
        for row in rows:
            ws.append([
                row.set_name,
                row.fixture,
                row.universe,
                row.address,
                row.end_address,
                row.type,
                row.channel_count,
                row.location,
                row.wattage,
                row.weight,
                row.notes,
                row.firmware
            ])

        # Save to BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)

        return send_file(output,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True,
                         download_name=f"{patch.name or 'patch'}.xlsx")

    except Exception as e:
        current_app.logger.exception("Excel export failed")
        return jsonify({'error': str(e)}), 500






# ───────────── LABEL TEMPLATES ───────────── #

from flask import jsonify, request
from .models import PatchSheet, PatchRow, LabelTemplate  # adjust imports

# 1a. List all patch sheets
@bp.route('/api/patch-sheets', methods=['GET'])
def list_all_patch_sheets():
    # fall back to ordering by primary key if you don't have a created_at
    sheets = PatchSheet.query.order_by(PatchSheet.id.desc()).all()
    return jsonify([
        { 'id': s.id, 'name': s.name } for s in sheets
    ]), 200

# 1b. List rows for one sheet
@bp.route('/api/patch-sheets/<int:sheet_id>/rows', methods=['GET'])
def list_rows_for_sheet(sheet_id):
    rows = PatchRow.query.filter_by(patch_sheet_id=sheet_id).all()
    return jsonify([
        {
          'id':    r.id,
          'fixture_number': r.fixture_number,
          'type': r.fixture_type,
          'location': r.location,
          # …add whatever other fields you’ll let the user put on a label…
        }
        for r in rows
    ]), 200

# 1c. (Later) CRUD for label-layout templates
@bp.route('/api/label-templates', methods=['GET','POST'])
def label_templates():
    if request.method == 'GET':
        templates = LabelTemplate.query.order_by(LabelTemplate.name).all()
        return jsonify([{
            'id':   t.id,
            'name': t.name,
            'config': t.config_json  # JSON blob of your saved field positions, fonts, etc.
        } for t in templates]), 200

    # POST → create new template; body should include name & config_json
    data = request.get_json()
    t = LabelTemplate(name=data['name'], config_json=data['config'])
    db.session.add(t); db.session.commit()
    return jsonify({'id': t.id}), 201

# UPDATE (rename or reconfigure) a template
@bp.route('/api/label-templates/<int:tpl_id>', methods=['PUT'])
def update_label_template(tpl_id):
    data = request.get_json()
    tpl = LabelTemplate.query.get_or_404(tpl_id)

    # rename?
    if 'name' in data:
        tpl.name = data['name']

    # reconfigure?
    if 'config' in data:
        tpl.config_json = data['config']

    db.session.commit()
    return jsonify({ 'success': True }), 200

# DELETE a template (optional, but handy)
@bp.route('/api/label-templates/<int:tpl_id>', methods=['DELETE'])
def delete_label_template(tpl_id):
    tpl = LabelTemplate.query.get_or_404(tpl_id)
    db.session.delete(tpl)
    db.session.commit()
    return jsonify({ 'success': True }), 200


# ── Network / IP config ───────────────────────────────────────────────────────

def _run_ps(cmd):
    r = subprocess.run(
        ['powershell', '-NoProfile', '-NonInteractive', '-Command', cmd],
        capture_output=True, text=True, timeout=20
    )
    return r.stdout.strip(), r.stderr.strip(), r.returncode


@bp.route('/api/network/interfaces', methods=['GET'])
def network_interfaces():
    ps = r"""
$result = Get-NetAdapter | Where-Object { $_.Status -ne 'Not Present' } | ForEach-Object {
    $n = $_.Name
    $ip  = Get-NetIPAddress -InterfaceAlias $n -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -First 1
    $gw  = (Get-NetRoute -InterfaceAlias $n -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Select-Object -First 1).NextHop
    $ifc = Get-NetIPInterface -InterfaceAlias $n -AddressFamily IPv4 -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        name        = $_.Name
        description = $_.InterfaceDescription
        status      = [string]$_.Status
        mac         = $_.MacAddress
        ip          = if ($ip)  { $ip.IPAddress }       else { '' }
        prefix      = if ($ip)  { [int]$ip.PrefixLength } else { 24 }
        gateway     = if ($gw)  { $gw }                 else { '' }
        dhcp        = ($ifc -and $ifc.Dhcp -eq 'Enabled')
    }
}
@($result) | ConvertTo-Json -Compress
"""
    out, err, code = _run_ps(ps)
    if code != 0:
        return jsonify({'error': err or 'PowerShell error'}), 500
    try:
        data = json.loads(out) if out else []
        if isinstance(data, dict):
            data = [data]
    except Exception:
        return jsonify({'error': 'Failed to parse adapter list'}), 500
    return jsonify(data)


@bp.route('/api/network/apply', methods=['POST'])
def network_apply():
    body = request.get_json(force=True)
    adapter = body.get('adapter', '').strip()
    ip      = body.get('ip', '').strip()
    prefix  = int(body.get('prefix', 24))
    gateway = body.get('gateway', '').strip()

    if not adapter or not ip:
        return jsonify({'error': 'adapter and ip are required'}), 400

    gw_line = f"-DefaultGateway '{gateway}'" if gateway else ''
    ps = f"""
$ErrorActionPreference = 'Stop'
Set-NetIPInterface -InterfaceAlias '{adapter}' -AddressFamily IPv4 -Dhcp Disabled -ErrorAction SilentlyContinue
Get-NetIPAddress   -InterfaceAlias '{adapter}' -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
Get-NetRoute       -InterfaceAlias '{adapter}' -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
New-NetIPAddress   -InterfaceAlias '{adapter}' -IPAddress '{ip}' -PrefixLength {prefix} {gw_line}
"""
    out, err, code = _run_ps(ps)
    if code != 0:
        admin = 'access' in err.lower() or 'administrator' in err.lower() or 'privileged' in err.lower()
        return jsonify({'error': err or 'Apply failed', 'adminRequired': admin}), 403 if admin else 500
    return jsonify({'success': True})


@bp.route('/api/network/dhcp', methods=['POST'])
def network_dhcp():
    body = request.get_json(force=True)
    adapter = body.get('adapter', '').strip()
    if not adapter:
        return jsonify({'error': 'adapter is required'}), 400

    ps = f"""
$ErrorActionPreference = 'Stop'
Set-NetIPInterface -InterfaceAlias '{adapter}' -AddressFamily IPv4 -Dhcp Enabled
Get-NetIPAddress -InterfaceAlias '{adapter}' -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {{ $_.PrefixOrigin -ne 'Dhcp' }} |
    Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
Get-NetRoute -InterfaceAlias '{adapter}' -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
"""
    out, err, code = _run_ps(ps)
    if code != 0:
        admin = 'access' in err.lower() or 'administrator' in err.lower() or 'privileged' in err.lower()
        return jsonify({'error': err or 'DHCP switch failed', 'adminRequired': admin}), 403 if admin else 500
    return jsonify({'success': True})


# ── Node discovery & config ───────────────────────────────────────────────────

# MAC OUI → manufacturer (key vendors for AV/IT/lighting networks)
_OUI = {
    # Ubiquiti
    '00:15:6d': 'Ubiquiti', '00:27:22': 'Ubiquiti', '04:18:d6': 'Ubiquiti',
    '18:e8:29': 'Ubiquiti', '24:a4:3c': 'Ubiquiti', '44:d9:e7': 'Ubiquiti',
    '68:72:51': 'Ubiquiti', '70:a7:41': 'Ubiquiti', '74:83:c8': 'Ubiquiti',
    '78:8a:20': 'Ubiquiti', '80:2a:a8': 'Ubiquiti', 'ac:8b:a9': 'Ubiquiti',
    'b4:fb:e4': 'Ubiquiti', 'dc:9f:db': 'Ubiquiti', 'e0:63:da': 'Ubiquiti',
    'f0:9f:c2': 'Ubiquiti', 'fc:ec:da': 'Ubiquiti', '18:e8:29': 'Ubiquiti',
    # Cisco / Meraki
    '00:00:0c': 'Cisco', '00:1a:a1': 'Cisco', '00:26:cb': 'Cisco',
    '88:f0:31': 'Cisco',  '34:db:fd': 'Meraki',  'e8:65:d4': 'Meraki',
    # Netgear
    '00:09:5b': 'Netgear', '20:e5:2a': 'Netgear', 'a0:40:a0': 'Netgear',
    # TP-Link
    '14:cc:20': 'TP-Link', '50:c7:bf': 'TP-Link', 'ac:84:c6': 'TP-Link',
    # Philips Hue / Signify
    '00:17:88': 'Philips Hue', 'ec:b5:fa': 'Philips Hue',
    # Apple
    '00:17:f2': 'Apple', '28:cf:da': 'Apple', '3c:15:c2': 'Apple',
    'a8:86:dd': 'Apple', 'f8:ff:c2': 'Apple',
    # Raspberry Pi
    'b8:27:eb': 'Raspberry Pi', 'dc:a6:32': 'Raspberry Pi', 'e4:5f:01': 'Raspberry Pi',
    # Dell
    '00:14:22': 'Dell', '1c:69:7a': 'Dell', 'f8:bc:12': 'Dell',
    # HP
    '00:17:a4': 'HP', '3c:d9:2b': 'HP', 'b4:99:ba': 'HP',
}

def _oui_lookup(mac_str):
    if not mac_str:
        return None
    norm = mac_str.lower().replace('-', ':')
    return _OUI.get(':'.join(norm.split(':')[:3]))


def _is_probe_target(ip_str):
    try:
        a = ipaddress.IPv4Address(ip_str)
        return not (a.is_multicast or a.is_loopback or a.is_unspecified or
                    a.packed[-1] == 255)
    except Exception:
        return False


def _arp_entries():
    """Return list of {ip, mac} from Windows ARP cache."""
    result = subprocess.run(['arp', '-a'], capture_output=True, text=True)
    entries = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and _is_probe_target(parts[0]):
            mac = parts[1] if re.match(r'^[0-9a-f]{2}[-:]', parts[1], re.I) else ''
            entries[parts[0]] = mac.lower().replace('-', ':')
    return entries  # {ip: mac}


def _html_title(html):
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    return re.sub(r'\s+', ' ', m.group(1)).strip() if m else ''


def _resolve_hostname(ip):
    """Non-blocking reverse DNS — runs in its own thread so timeout is enforced."""
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ''


def _probe_one(ip, mac, hostname_futures):
    """HTTP-probe an IP, return device dict."""
    entry = {
        'ip':           ip,
        'mac':          mac,
        'manufacturer': _oui_lookup(mac),
        'type':         'host',
        'title':        '',
        'hostname':     '',
        'model':        '',
        'firmware':     '',
    }

    # HTTP probe — (connect=0.8s, read=1.5s)
    try:
        resp = req.get(f'http://{ip}/', timeout=(0.8, 1.5), allow_redirects=True)
        html = resp.text
        low  = html.lower()
        entry['title'] = _html_title(html)

        if any(k in low for k in ('gigacore', 'lumios', 'luminex')):
            entry['type'] = 'gigacore'
        elif any(k in low for k in ('swisson', 'xnd-', '>xnd<', 'xnd ')):
            entry['type'] = 'swisson'
        elif any(k in low for k in ('ubnt', 'ubiquiti', 'airmax', 'unifi',
                                     'edgerouter', 'edgeswitch', 'gigabeam', 'uisp')):
            entry['type'] = 'ubiquiti'
        elif any(k in low for k in ('router', 'gateway', 'netgear', 'linksys',
                                     'd-link', 'tp-link', 'tplink', 'asus router',
                                     'airport', 'openwrt', 'dd-wrt')):
            entry['type'] = 'router'
    except Exception:
        pass  # no web interface — stays as 'host'

    # OUI override: Ubiquiti by MAC when HTTP didn't identify it
    if entry['manufacturer'] == 'Ubiquiti' and entry['type'] == 'host':
        entry['type'] = 'ubiquiti'

    return entry


# ── Ubiquiti UDP discovery (port 10001) ───────────────────────────────────────

def _ubiquiti_discover(timeout=2):
    """
    Broadcast Ubiquiti discovery packet and collect responses.
    Returns {ip: {mac, model, firmware, hostname, ...}}
    """
    UBNT_PORT   = 10001
    MAGIC_V1    = b'\x01\x00\x00\x00'
    results     = {}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.3)
        sock.bind(('', 0))
        sock.sendto(MAGIC_V1, ('255.255.255.255', UBNT_PORT))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, (addr, _) = sock.recvfrom(4096)
                parsed = _parse_ubnt(data)
                if parsed:
                    results[addr] = parsed
            except socket.timeout:
                pass
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return results


def _parse_ubnt(data):
    """Parse Ubiquiti TLV discovery response."""
    if len(data) < 4 or data[0] not in (1, 2):
        return None
    payload_len = struct.unpack_from('>H', data, 2)[0]
    payload = data[4:4 + payload_len]
    info = {}
    pos = 0
    while pos + 3 <= len(payload):
        t = payload[pos]
        l = struct.unpack_from('>H', payload, pos + 1)[0]
        v = payload[pos + 3:pos + 3 + l]
        pos += 3 + l
        if   t == 0x01 and l == 6:  info['mac']      = ':'.join(f'{b:02x}' for b in v)
        elif t == 0x02 and l >= 10: info['mac']      = ':'.join(f'{b:02x}' for b in v[:6])
        elif t == 0x03:             info['firmware']  = v.decode('utf-8', errors='replace').rstrip('\x00')
        elif t == 0x0b:             info['ssid']      = v.decode('utf-8', errors='replace').rstrip('\x00')
        elif t == 0x0c:             info['model']     = v.decode('utf-8', errors='replace').rstrip('\x00')
        elif t == 0x10:             info['hostname']  = v.decode('utf-8', errors='replace').rstrip('\x00')
        elif t == 0x13:             info['platform']  = v.decode('utf-8', errors='replace').rstrip('\x00')
    return info or None


# ── Network health analysis ───────────────────────────────────────────────────

def _network_health(arp_map, devices):
    """Return list of health issue dicts."""
    issues = []

    # APIPA: 169.254.x.x = failed DHCP
    apipa = [ip for ip in arp_map if ip.startswith('169.254.')]
    if apipa:
        issues.append({
            'level':   'warning',
            'type':    'apipa',
            'message': f'{len(apipa)} device(s) have APIPA addresses (169.254.x.x) — DHCP failure',
            'ips':     apipa,
        })

    # IP conflict: same IP → multiple different MACs across ARP cache entries
    ip_macs = {}
    for ip, mac in arp_map.items():
        if mac and mac not in ('ff:ff:ff:ff:ff:ff', '00:00:00:00:00:00', ''):
            ip_macs.setdefault(ip, set()).add(mac)
    for ip, macs in ip_macs.items():
        if len(macs) > 1:
            issues.append({
                'level':   'error',
                'type':    'ip_conflict',
                'message': f'IP conflict: {ip} is claimed by {len(macs)} different MAC addresses',
                'ips':     [ip],
                'macs':    list(macs),
            })

    # Duplicate MACs: same MAC → multiple IPs (unusual, could be VRRP/HSRP or spoofing)
    mac_ips = {}
    for ip, mac in arp_map.items():
        if mac and mac not in ('ff:ff:ff:ff:ff:ff', '00:00:00:00:00:00', ''):
            mac_ips.setdefault(mac, set()).add(ip)
    for mac, ips in mac_ips.items():
        if len(ips) > 1:
            issues.append({
                'level':   'info',
                'type':    'duplicate_mac',
                'message': f'MAC {mac} appears on {len(ips)} IPs — may be VRRP/HSRP or a config issue',
                'ips':     list(ips),
            })

    return issues


@bp.route('/api/nodes/scan', methods=['GET'])
def nodes_scan():
    t0 = time.time()

    # Phase 1: ARP cache + Ubiquiti UDP discovery (parallel, capped at 1.5 s)
    with ThreadPoolExecutor(max_workers=2) as boot:
        ubnt_fut = boot.submit(_ubiquiti_discover, 1.5)
        arp_map  = _arp_entries()
        ubnt_map = ubnt_fut.result()

    # Merge Ubiquiti-only IPs
    for ip, info in ubnt_map.items():
        if ip not in arp_map:
            arp_map[ip] = info.get('mac', '')

    # Phase 2: DNS resolution (daemon pool — we don't wait on it)
    dns_pool    = ThreadPoolExecutor(max_workers=30)
    dns_futures = {ip: dns_pool.submit(_resolve_hostname, ip) for ip in arp_map}
    dns_pool.shutdown(wait=False)  # fire-and-forget; collect what finishes in time

    # Phase 3: HTTP probes (capped per-request at 0.8 s connect + 1.5 s read)
    devices = []
    with ThreadPoolExecutor(max_workers=40) as pool:
        probe_futures = {
            pool.submit(_probe_one, ip, mac, None): ip
            for ip, mac in arp_map.items()
        }
        for fut in as_completed(probe_futures):
            try:
                devices.append(fut.result())
            except Exception:
                pass

    # Collect hostnames that finished during the HTTP-probe window
    for d in devices:
        try:
            d['hostname'] = dns_futures[d['ip']].result(timeout=0)
        except Exception:
            d['hostname'] = ''

    # Enrich Ubiquiti devices with UDP discovery data
    for d in devices:
        if d['ip'] in ubnt_map:
            u = ubnt_map[d['ip']]
            d['type']     = 'ubiquiti'
            d['model']    = u.get('model', d.get('model', ''))
            d['firmware'] = u.get('firmware', d.get('firmware', ''))
            if not d['hostname']:
                d['hostname'] = u.get('hostname', '')

    devices.sort(key=lambda d: [int(p) for p in d['ip'].split('.')])
    health = _network_health(arp_map, devices)

    return jsonify({
        'devices': devices,
        'health':  health,
        'elapsed': round(time.time() - t0, 2),
    })


# ── GigaCore config helpers ───────────────────────────────────────────────────

def _gigacore_read(ip, username='admin', password='admin'):
    """
    Try GigaCore REST API (firmware 3.x+).
    POST /api/rest/v1/login → bearer token → GET /api/rest/v1/ports
    Falls back to a note if REST is unavailable (older firmware).
    NOTE: Endpoint paths may vary by firmware — verify against your unit.
    """
    base = f'http://{ip}'
    try:
        # Authenticate
        login = req.post(f'{base}/api/rest/v1/login',
                         json={'username': username, 'password': password},
                         timeout=5)
        if login.status_code == 200:
            token = login.json().get('token', '')
            hdrs  = {'Authorization': f'Bearer {token}'}

            # Device info
            info_resp = req.get(f'{base}/api/rest/v1/device', headers=hdrs, timeout=5)
            info = info_resp.json() if info_resp.ok else {}

            # Port / universe config
            ports_resp = req.get(f'{base}/api/rest/v1/ports', headers=hdrs, timeout=5)
            if ports_resp.ok:
                return {
                    'method': 'rest',
                    'device': info,
                    'ports':  ports_resp.json(),
                    'token':  token,
                }
        elif login.status_code == 404:
            return {'method': 'none', 'error': 'REST API not found — firmware may be older than 3.x'}
        else:
            return {'method': 'none', 'error': f'Auth failed ({login.status_code}) — check credentials'}
    except req.exceptions.ConnectionError:
        return {'method': 'none', 'error': 'Could not connect'}
    except Exception as e:
        return {'method': 'none', 'error': str(e)}


def _gigacore_write(ip, token, port_id, universe, protocol, merge_mode):
    """
    PUT /api/rest/v1/ports/{id}
    NOTE: Field names may vary by firmware — verify against your unit.
    """
    hdrs = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    payload = {
        'universe':  universe,
        'protocol':  protocol,    # 'sacn' | 'artnet'
        'mergeMode': merge_mode,  # 'htp' | 'ltp'
    }
    resp = req.put(f'http://{ip}/api/rest/v1/ports/{port_id}',
                   json=payload, headers=hdrs, timeout=5)
    return resp.ok, resp.text


# ── Swisson XND config helpers ────────────────────────────────────────────────

# Known field-name patterns across XND firmware versions
_XND_PORT_RE = re.compile(
    r'(?:port|ch|output)[_\-]?(\d+)[_\-]?universe.*?value=["\'](\d+)["\']',
    re.I
)
_XND_PROTO_RE = re.compile(
    r'(?:port|ch|output)[_\-]?(\d+)[_\-]?(?:protocol|mode).*?value=["\']([^"\']+)["\']',
    re.I
)

def _swisson_read(ip, username='', password=''):
    """
    Fetch Swisson XND web interface and parse per-port config.
    Tries / first, then /config.html.
    NOTE: HTML field names vary by XND model/firmware — may need adjustment.
    """
    auth = (username, password) if username else None
    html = ''
    for path in ('/', '/config.html', '/index.html'):
        try:
            resp = req.get(f'http://{ip}{path}', auth=auth, timeout=5)
            if resp.ok and len(resp.text) > 200:
                html = resp.text
                break
        except Exception:
            continue

    if not html:
        return {'method': 'none', 'error': 'Could not load device web interface'}

    # Extract all <input>, <select> fields for port configuration
    inputs = re.findall(
        r'<(?:input|select)[^>]+name=["\']([^"\']+)["\'][^>]*(?:value=["\']([^"\']*)["\'])?',
        html, re.I
    )
    # Also grab <option selected> values
    selects = {}
    for sel_match in re.finditer(
        r'<select[^>]+name=["\']([^"\']+)["\'][^>]*>(.*?)</select>',
        html, re.I | re.S
    ):
        sel_name = sel_match.group(1)
        sel_body = sel_match.group(2)
        opt = re.search(r'<option[^>]+selected[^>]*value=["\']([^"\']*)["\']', sel_body, re.I)
        if opt:
            selects[sel_name] = opt.group(1)

    # Build port list from field names — common patterns:
    # port_N_universe / portN_universe / chN_universe / outputN_universe
    port_map = {}
    for name, value in inputs:
        m = re.match(r'(?:port|ch|output|universe_)[\-_]?(\d+)[\-_]?(.*)', name, re.I)
        if m:
            idx, field = m.group(1), m.group(2).lower()
            port_map.setdefault(idx, {})['raw_' + field] = selects.get(name, value)

    # Normalise fields into known keys
    ports = []
    for idx in sorted(port_map.keys(), key=int):
        raw = port_map[idx]
        p = {'port': int(idx)}
        for k, v in raw.items():
            if 'universe' in k:
                p['universe'] = v
            elif 'protocol' in k or 'mode' in k:
                p['protocol'] = v
            elif 'merge' in k:
                p['mergeMode'] = v
            else:
                p[k] = v
        ports.append(p)

    return {
        'method':    'scrape',
        'ports':     ports,
        'allFields': {**dict(inputs), **selects},  # raw dump for debugging
        'html_snippet': html[:3000],               # first 3 KB for inspection
    }


def _swisson_write(ip, port_id, universe, protocol, merge_mode, username='', password=''):
    """
    POST port config back to Swisson XND web form.
    NOTE: Form action path and field names depend on firmware — verify first.
    """
    auth = (username, password) if username else None
    payload = {
        f'port_{port_id}_universe':  universe,
        f'port_{port_id}_protocol':  protocol,
        f'port_{port_id}_mergeMode': merge_mode,
    }
    try:
        resp = req.post(f'http://{ip}/config', data=payload, auth=auth, timeout=5)
        return resp.ok, resp.text
    except Exception as e:
        return False, str(e)


# ── Node routes ───────────────────────────────────────────────────────────────

@bp.route('/api/nodes/<ip>/config', methods=['GET'])
def node_config_get(ip):
    if not _is_probe_target(ip):
        return jsonify({'error': 'Invalid IP'}), 400
    device_type = request.args.get('type', '')
    username    = request.args.get('user', 'admin')
    password    = request.args.get('pass', 'admin')

    if device_type == 'gigacore':
        return jsonify(_gigacore_read(ip, username, password))
    elif device_type == 'swisson':
        return jsonify(_swisson_read(ip, username, password))
    return jsonify({'error': 'Unknown device type'}), 400


@bp.route('/api/nodes/<ip>/config', methods=['PUT'])
def node_config_put(ip):
    if not _is_probe_target(ip):
        return jsonify({'error': 'Invalid IP'}), 400
    body        = request.get_json(force=True)
    device_type = body.get('type', '')
    port_id     = body.get('portId')
    universe    = body.get('universe')
    protocol    = body.get('protocol', 'sacn')
    merge_mode  = body.get('mergeMode', 'htp')
    username    = body.get('user', 'admin')
    password    = body.get('pass', 'admin')
    token       = body.get('token', '')

    if device_type == 'gigacore':
        ok, text = _gigacore_write(ip, token, port_id, universe, protocol, merge_mode)
    elif device_type == 'swisson':
        ok, text = _swisson_write(ip, port_id, universe, protocol, merge_mode, username, password)
    else:
        return jsonify({'error': 'Unknown device type'}), 400

    if ok:
        return jsonify({'success': True})
    return jsonify({'error': text}), 500


# ── Serve built React app (desktop / production mode) ────────────────────────
@bp.route('/', defaults={'path': ''})
@bp.route('/<path:path>')
def serve_frontend(path):
    static_dir = os.environ.get('FIVE12_STATIC_DIR', _STATIC_DIR)
    if not static_dir or not os.path.isdir(static_dir):
        return 'Frontend not built. Run: npm run build inside the app/ folder.', 404
    full = os.path.join(static_dir, path)
    if path and os.path.isfile(full):
        return send_from_directory(static_dir, path)
    return send_from_directory(static_dir, 'index.html')