# File: backend/app/routes.py
from flask import Blueprint, request, jsonify, current_app
from .models import Show, PatchSheet, Fixture, PatchRow
from . import db

bp = Blueprint('api', __name__)

# ─── Shows ─────────────────────────────────────────────────────────────────────

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


# ─── Patch Sheets ───────────────────────────────────────────────────────────────

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


# ─── Fixtures Database ──────────────────────────────────────────────────────────

@bp.route('/api/fixtures', methods=['GET'])
def list_fixtures():
    fixtures = Fixture.query.order_by(Fixture.fixture).all()
    return jsonify([f.to_dict() for f in fixtures])


@bp.route('/api/fixtures', methods=['POST'])
def create_fixture():
    try:
        data = request.get_json(force=True)
        f = Fixture(
            fixture      = data.get('fixture', '').strip(),
            mode         = data.get('mode', '').strip(),
            notes        = data.get('notes', '').strip(),
            channel_count= data.get('channelCount', 0) or 0,
            wattage      = data.get('wattage', 0) or 0,
            weight       = data.get('weight', 0) or 0,
            firmware     = data.get('firmware', '').strip()
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
        f.fixture       = data.get('fixture', f.fixture).strip()
        f.mode          = data.get('mode', f.mode).strip()
        f.notes         = data.get('notes', f.notes).strip()
        f.channel_count = data.get('channelCount', f.channel_count) or f.channel_count
        f.wattage       = data.get('wattage', f.wattage) or f.wattage
        f.weight        = data.get('weight', f.weight) or f.weight
        f.firmware      = data.get('firmware', f.firmware).strip()
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


# ─── Patch Rows ─────────────────────────────────────────────────────────────────

@bp.route('/api/patch-sheets/<int:patch_id>/rows', methods=['GET'])
def list_patch_rows(patch_id):
    PatchSheet.query.get_or_404(patch_id)
    rows = (
        PatchRow.query
        .filter_by(patch_id=patch_id)
        .order_by(PatchRow.set_name)    # ← use set_name instead of set_number
        .all()
    )
    return jsonify([r.to_dict() for r in rows])

@bp.route('/api/patch-sheets/<int:patch_id>/rows', methods=['POST'])
def create_patch_row(patch_id):
    try:
        PatchSheet.query.get_or_404(patch_id)
        data = request.get_json(force=True)
        current_app.logger.debug("create_patch_row payload: %r", data)

        r = PatchRow(
            patch_id    = patch_id,
            set_name    = data.get('set') or None,
            fixture     = data.get('fixture'),
            universe    = data.get('universe'),
            address     = data.get('address'),
            end_address = data.get('endAddress'),
            type        = data.get('type'),
            mode        = data.get('mode'),
            channel_count = data.get('channelCount'),
            location    = data.get('location'),
            wattage     = data.get('wattage'),
            weight      = data.get('weight'),
            notes       = data.get('notes'),
            firmware    = data.get('firmware'),
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
        for field, attr in [
            ('set', 'set_name'),
            ('fixture', 'fixture'),
            ('universe', 'universe'),
            ('address', 'address'),
            ('endAddress', 'end_address'),
            ('type', 'type'),
            ('mode', 'mode'),
            ('channelCount', 'channel_count'),
            ('location', 'location'),
            ('wattage', 'wattage'),
            ('weight', 'weight'),
            ('notes', 'notes'),
            ('firmware', 'firmware'),
        ]:
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


@bp.route('/api/shows/<int:show_id>/patch-sheets/<int:patch_id>', methods=['GET'])
def get_patch_sheet(show_id, patch_id):
    # make sure the show exists
    Show.query.get_or_404(show_id)
    patch = PatchSheet.query.get_or_404(patch_id)
    return jsonify(patch.to_dict())