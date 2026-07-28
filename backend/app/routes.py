# File: backend/app/routes.py
import os
import subprocess
import json
import ipaddress
import re
import socket
import struct
import time
from urllib.parse import urlparse
import requests as req
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, request, jsonify, current_app, send_file, send_from_directory
from .models import Show, PatchSheet, Fixture, PatchRow, LabelTemplate
from . import db
from .patch_import import (read_table, detect_header_row, guess_mapping,
                           apply_mapping)
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
        if 'file' not in request.files:
            return {'error': 'No file uploaded'}, 400
        f = request.files['file']
        mapping = json.loads(request.form.get('mapping', '{}'))
        header_idx = int(request.form.get('headerRowIndex', 0))
        grid = read_table(f.read(), f.filename)
        if not grid:
            return {'error': 'The file appears to be empty.'}, 400
        headers = [('' if c is None else str(c)).strip()
                   for c in grid[header_idx]]
        data_rows = grid[header_idx + 1:]
        canonical_rows = apply_mapping(headers, data_rows, mapping)
        for row in canonical_rows:
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
        inserted = len(canonical_rows)
        return jsonify({'inserted': inserted,
                        'skipped': max(0, non_blank - inserted)})
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

# These three routes shell out to PowerShell and reconfigure a physical NIC. They
# are the only privileged writes in this blueprint, so they carry their own
# guards rather than relying on the loopback bind alone:
#
#   1. _run_ps() passes operator input as environment variables, never as
#      PowerShell source, so a value cannot become code (see _run_ps).
#   2. The adapter name is resolved against the live adapter list, so only a NIC
#      the machine actually has can be targeted.
#   3. Addresses go through the ipaddress module.
#   4. A browser-supplied cross-origin Origin header is rejected (_local_origin).
#
# Any one of these closes the injection; they are layered because the endpoint
# performs disruptive changes and is unauthenticated.

# Hosts a browser may name in Origin for a request we treat as first-party. The
# desktop shell loads http://127.0.0.1:<port>, and Vite dev serves localhost.
_LOCAL_ORIGIN_HOSTS = {'127.0.0.1', 'localhost', '::1', '[::1]'}


def _run_ps(cmd, params=None):
    """Run a PowerShell script, passing operator input via the environment.

    `params` values are exported as environment variables and referenced inside
    the script as $env:NAME. They are never interpolated into the script text,
    so no quoting or escaping is required and no value can be parsed as code —
    the shell receives them as data after parsing is complete.
    """
    env = os.environ.copy()
    if params:
        env.update({k: str(v) for k, v in params.items()})
    r = subprocess.run(
        ['powershell', '-NoProfile', '-NonInteractive', '-Command', cmd],
        capture_output=True, text=True, timeout=20, env=env
    )
    return r.stdout.strip(), r.stderr.strip(), r.returncode


def _local_origin():
    """False when a browser presents a cross-origin Origin on a state change.

    No CORS is configured, which blocks an attacker *reading* our responses but
    not the request arriving — a cross-origin POST with a simple content type is
    delivered without a preflight, and request.get_json(force=True) parses it
    regardless of Content-Type. For a NIC reconfigure the side effect is the
    whole payload, so the response being unreadable is no protection.

    The desktop UI reaches this route from the Electron *renderer* via Axios, so
    Chromium sends the renderer's loopback origin and it is matched below. The
    absent-Origin exception is for native callers — curl, scripts, the test
    client — which send no Origin at all. Only a header that is present and
    foreign is rejected.

    Note this is a *hostname* allowlist, not an exact-origin one: every loopback
    origin is trusted regardless of port or scheme. That is deliberate under the
    loopback desktop threat model — a public page keeps its public hostname in
    Origin, so the web CSRF path stays closed — but it does mean another service
    already running on loopback is treated as first-party. Exact scheme/port
    matching, or real authentication, is the stronger design when this endpoint
    stops being loopback-only.
    """
    origin = request.headers.get('Origin')
    if not origin:
        return True
    try:
        host = urlparse(origin).hostname
    except ValueError:
        return False
    return host in _LOCAL_ORIGIN_HOSTS


def _adapter_names():
    """Names of the adapters this machine actually has, for allowlisting."""
    out, _, code = _run_ps(
        "@(Get-NetAdapter | Where-Object { $_.Status -ne 'Not Present' } |"
        " ForEach-Object { $_.Name }) | ConvertTo-Json -Compress"
    )
    if code != 0 or not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    if isinstance(data, str):
        return [data]
    return [str(n) for n in data] if isinstance(data, list) else []


def _valid_ipv4(value):
    try:
        ipaddress.IPv4Address(value)
        return True
    except ValueError:
        return False


def _ps_failure(out, err, code, fallback):
    """Build an operator-usable message from a failed PowerShell run.

    [BENCH 2026-07-28] The DHCP route returned a bare "DHCP switch failed" on a
    real rig: PowerShell exited non-zero having written nothing to stderr, and
    the route forwarded only stderr, so everything diagnostic was discarded. An
    operator at a console got a failure with nothing to act on, and neither did
    the person debugging it. Fall through stderr -> stdout -> exit code so there
    is always something concrete to report.
    """
    detail = (err or '').strip() or (out or '').strip()
    if detail:
        return detail
    return f'{fallback} (PowerShell exited {code} with no output)'


def _network_tools_enabled():
    """Honour the FIVE12_NETWORK_TOOLS kill switch on this blueprint too.

    app/__init__.py gates network_routes.py (subnets, devices, sACN) behind
    ENABLE_NETWORK_TOOLS and its comment states the /api/network/* routes "simply
    don't exist" when it is off. That was not true of these three: they live on
    the always-registered routes blueprint, so the switch left the only endpoints
    that execute PowerShell reachable — including on a hosted deploy, where the
    switch is precisely what an operator would set. They check it themselves now.
    """
    return bool(current_app.config.get('ENABLE_NETWORK_TOOLS'))


@bp.route('/api/network/interfaces', methods=['GET'])
def network_interfaces():
    if not _network_tools_enabled():
        return jsonify({'error': 'Network tools are disabled'}), 404
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
    if not _network_tools_enabled():
        return jsonify({'error': 'Network tools are disabled'}), 404
    if not _local_origin():
        return jsonify({'error': 'Cross-origin request rejected'}), 403

    body = request.get_json(force=True, silent=True) or {}
    adapter = str(body.get('adapter', '')).strip()
    ip      = str(body.get('ip', '')).strip()
    gateway = str(body.get('gateway', '')).strip()

    if not adapter or not ip:
        return jsonify({'error': 'adapter and ip are required'}), 400

    try:
        prefix = int(body.get('prefix', 24))
    except (TypeError, ValueError):
        return jsonify({'error': 'prefix must be a number'}), 400
    if not 1 <= prefix <= 32:
        return jsonify({'error': 'prefix must be between 1 and 32'}), 400

    if not _valid_ipv4(ip):
        return jsonify({'error': 'ip is not a valid IPv4 address'}), 400
    if gateway and not _valid_ipv4(gateway):
        return jsonify({'error': 'gateway is not a valid IPv4 address'}), 400

    # Allowlist by construction: only a NIC this machine reports can be named.
    known = _adapter_names()
    if not known:
        return jsonify({'error': 'Could not enumerate network adapters'}), 500
    if adapter not in known:
        return jsonify({'error': f'Unknown network adapter: {adapter}'}), 400

    # $env: references, not interpolation — see _run_ps.
    gw_line = "-DefaultGateway $env:FIVE12_GATEWAY" if gateway else ''
    ps = f"""
$ErrorActionPreference = 'Stop'
Set-NetIPInterface -InterfaceAlias $env:FIVE12_ADAPTER -AddressFamily IPv4 -Dhcp Disabled -ErrorAction SilentlyContinue
Get-NetIPAddress   -InterfaceAlias $env:FIVE12_ADAPTER -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
Get-NetRoute       -InterfaceAlias $env:FIVE12_ADAPTER -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
New-NetIPAddress   -InterfaceAlias $env:FIVE12_ADAPTER -IPAddress $env:FIVE12_IP -PrefixLength {prefix} {gw_line}
"""
    out, err, code = _run_ps(ps, {
        'FIVE12_ADAPTER': adapter,
        'FIVE12_IP': ip,
        'FIVE12_GATEWAY': gateway,
    })
    if code != 0:
        detail = _ps_failure(out, err, code, 'Apply failed')
        admin = any(w in detail.lower()
                    for w in ('access is denied', 'administrator', 'privileged'))
        current_app.logger.error('network_apply failed (exit %s): %s', code, detail)
        return jsonify({'error': detail, 'adminRequired': admin}), 403 if admin else 500
    return jsonify({'success': True})


@bp.route('/api/network/dhcp', methods=['POST'])
def network_dhcp():
    if not _network_tools_enabled():
        return jsonify({'error': 'Network tools are disabled'}), 404
    if not _local_origin():
        return jsonify({'error': 'Cross-origin request rejected'}), 403

    body = request.get_json(force=True, silent=True) or {}
    adapter = str(body.get('adapter', '')).strip()
    if not adapter:
        return jsonify({'error': 'adapter is required'}), 400

    known = _adapter_names()
    if not known:
        return jsonify({'error': 'Could not enumerate network adapters'}), 500
    if adapter not in known:
        return jsonify({'error': f'Unknown network adapter: {adapter}'}), 400

    ps = """
$ErrorActionPreference = 'Stop'
Set-NetIPInterface -InterfaceAlias $env:FIVE12_ADAPTER -AddressFamily IPv4 -Dhcp Enabled
Get-NetIPAddress -InterfaceAlias $env:FIVE12_ADAPTER -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.PrefixOrigin -ne 'Dhcp' } |
    Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
Get-NetRoute -InterfaceAlias $env:FIVE12_ADAPTER -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
"""
    out, err, code = _run_ps(ps, {'FIVE12_ADAPTER': adapter})
    if code != 0:
        detail = _ps_failure(out, err, code, 'DHCP switch failed')
        admin = any(w in detail.lower()
                    for w in ('access is denied', 'administrator', 'privileged'))
        current_app.logger.error('network_dhcp failed (exit %s): %s', code, detail)
        return jsonify({'error': detail, 'adminRequired': admin}), 403 if admin else 500
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