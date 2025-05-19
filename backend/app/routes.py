# File: backend/app/routes.py
from flask import Blueprint, request, jsonify, current_app
from .models import Show, PatchSheet, Fixture, PatchRow
from . import db
import pandas as pd
from io import BytesIO
import re

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
def list_patch_sheets(show_id):
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

@bp.route('/api/shows/<int:show_id>/patch-sheets/<int:patch_id>', methods=['GET'])
def get_patch_sheet(show_id, patch_id):
    Show.query.get_or_404(show_id)
    patch = PatchSheet.query.get_or_404(patch_id)
    return jsonify(patch.to_dict())

# ───────────── PATCH ROWS ───────────── #

@bp.route('/api/patch-sheets/<int:patch_id>/rows', methods=['GET'])
def list_patch_rows(patch_id):
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
        f = Fixture(
            fixture=data.get('fixture', '').strip(),
            notes=data.get('notes', '').strip(),
            channel_count=data.get('channelCount', 0),
            wattage=data.get('wattage', 0),
            weight=data.get('weight', 0),
            firmware=data.get('firmware', '').strip()
        )
        db.session.add(f)
        db.session.commit()
        return jsonify(f.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Failed to create fixture")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/fixtures/<int:id>', methods=['PUT'])
def update_fixture(id):
    try:
        f = Fixture.query.get_or_404(id)
        data = request.get_json(force=True)
        f.fixture = data.get('fixture', f.fixture).strip()
        f.notes = data.get('notes', f.notes).strip()
        f.channel_count = data.get('channelCount', f.channel_count)
        f.wattage = data.get('wattage', f.wattage)
        f.weight = data.get('weight', f.weight)
        f.firmware = data.get('firmware', f.firmware).strip()
        db.session.commit()
        return jsonify(f.to_dict())
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Failed to update fixture")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/fixtures/<int:id>', methods=['DELETE'])
def delete_fixture(id):
    f = Fixture.query.get_or_404(id)
    db.session.delete(f)
    db.session.commit()
    return '', 204

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

    except Exception as e:
        current_app.logger.exception("Fixture import failed")
        return jsonify({'error': str(e)}), 500