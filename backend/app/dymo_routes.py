from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import desc

from . import db
from .models import DymoTemplate, DymoCsvSource
from .dymo_templates import extract_variables

dymo = Blueprint('dymo', __name__, url_prefix='/api/dymo-templates')


@dymo.post('')
def upload_template():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    xml = f.read().decode('utf-8-sig', errors='replace')
    try:
        variables = extract_variables(xml)
    except ValueError:
        return jsonify({'error': 'Not a valid DYMO label file'}), 400
    if not variables:
        return jsonify({'error': 'template has no named variables — name the '
                                 'text objects in DYMO Connect'}), 400
    name = (request.form.get('name') or '').strip()
    if not name:
        name = (f.filename or 'Untitled').rsplit('.', 1)[0]
    name = name[:120]
    t = DymoTemplate(name=name, label_xml=xml, variables=variables,
                     created_at=datetime.utcnow())
    db.session.add(t)
    db.session.commit()
    return jsonify(t.to_dict()), 201


@dymo.get('')
def list_templates():
    ts = DymoTemplate.query.order_by(DymoTemplate.name).all()
    return jsonify([t.to_dict() for t in ts])


@dymo.get('/<int:tid>')
def get_template(tid):
    return jsonify(DymoTemplate.query.get_or_404(tid).to_dict(include_xml=True))


@dymo.put('/<int:tid>/mapping')
def save_mapping(tid):
    t = DymoTemplate.query.get_or_404(tid)
    data = request.get_json(silent=True) or {}
    source, mapping = data.get('source'), data.get('mapping')
    if source not in ('patch', 'csv') or not isinstance(mapping, dict):
        return jsonify({'error': "source must be 'patch'|'csv' with a mapping dict"}), 400
    merged = dict(t.saved_mappings or {})
    merged[source] = mapping
    t.saved_mappings = merged
    db.session.commit()
    return jsonify(t.to_dict())


@dymo.delete('/<int:tid>')
def delete_template(tid):
    t = DymoTemplate.query.get_or_404(tid)
    db.session.delete(t)
    db.session.commit()
    return jsonify({'deleted': tid})


CSV_SOURCE_CAP = 20

csv_sources = Blueprint('dymo_csv', __name__, url_prefix='/api/dymo-csv-sources')


@csv_sources.get('')
def list_csv_sources():
    ss = (DymoCsvSource.query
          .order_by(desc(DymoCsvSource.created_at), desc(DymoCsvSource.id)).all())
    return jsonify([s.to_dict() for s in ss])


@csv_sources.get('/<int:sid>')
def get_csv_source(sid):
    return jsonify(DymoCsvSource.query.get_or_404(sid).to_dict(include_rows=True))


@csv_sources.post('')
def save_csv_source():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()[:200]
    headers, rows = data.get('headers'), data.get('rows')
    if not name or not isinstance(headers, list) or not isinstance(rows, list):
        return jsonify({'error': 'name (non-empty), headers (list) and rows (list) are required'}), 400

    existing = DymoCsvSource.query.filter_by(name=name).first()
    created = existing is None
    s = existing or DymoCsvSource(name=name)
    s.headers = headers
    s.rows = rows
    s.row_count = len(rows)
    s.created_at = datetime.utcnow()
    if created:
        db.session.add(s)
    db.session.flush()  # assign s.id before the cap query

    # cap: keep the CSV_SOURCE_CAP newest, delete the rest
    stale = (DymoCsvSource.query
             .order_by(desc(DymoCsvSource.created_at), desc(DymoCsvSource.id))
             .offset(CSV_SOURCE_CAP).all())
    for old in stale:
        db.session.delete(old)

    db.session.commit()
    return jsonify(s.to_dict()), (201 if created else 200)


@csv_sources.delete('/<int:sid>')
def delete_csv_source(sid):
    s = DymoCsvSource.query.get_or_404(sid)
    db.session.delete(s)
    db.session.commit()
    return jsonify({'deleted': sid})
