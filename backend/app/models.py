# backend/app/models.py
from . import db

class Show(db.Model):
    __tablename__ = 'shows'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    patches = db.relationship('PatchSheet', back_populates='show', cascade='all, delete-orphan')

    def to_dict(self):
        return {'id': self.id, 'name': self.name}

class PatchSheet(db.Model):
    __tablename__ = 'patch_sheets'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    show_id = db.Column(db.Integer, db.ForeignKey('shows.id'), nullable=False)
    show = db.relationship('Show', back_populates='patches')

    rows = db.relationship('PatchRow', backref='patch', lazy=True)  # ✅ Add this line
   
    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'show_id': self.show_id}


# backend/app/models.py
class Fixture(db.Model):
    __tablename__ = 'fixtures'
    id = db.Column(db.Integer, primary_key=True)
    fixture = db.Column(db.String(120), nullable=False)
    
    channel_count = db.Column(db.Integer, nullable=False)
    wattage       = db.Column(db.Integer, nullable=False)
    weight        = db.Column(db.Integer, nullable=False)
    firmware      = db.Column(db.String(120), nullable=True)
    notes         = db.Column(db.Text,    nullable=True)       # ← New!
    
    def to_dict(self):
        return {
            'id': self.id,
            'fixture': self.fixture,
            
            'channelCount': self.channel_count,
            'wattage': self.wattage,
            'weight': self.weight,
            'firmware': self.firmware,
             'notes': self.notes,
        }
    


class PatchRow(db.Model):
    __tablename__ = 'patch_rows'
    id            = db.Column(db.Integer, primary_key=True)
    patch_id      = db.Column(db.Integer, db.ForeignKey('patch_sheets.id'), nullable=False)
    set_name      = db.Column(db.String(50), nullable=True)
    fixture       = db.Column(db.String(50), nullable=True)
    universe      = db.Column(db.Integer, nullable=True)
    address       = db.Column(db.Integer, nullable=True)
    end_address   = db.Column(db.Integer, nullable=True)
    type          = db.Column(db.String(120), nullable=True)
    channel_count = db.Column(db.Integer, nullable=True)
    location      = db.Column(db.String(120), nullable=True)
    wattage       = db.Column(db.String(50), nullable=True)
    weight        = db.Column(db.String(50), nullable=True)
    notes         = db.Column(db.Text, nullable=True)
    firmware      = db.Column(db.String(120), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'patchId': self.patch_id,
            'set': self.set_name,
            'fixture': self.fixture,
            'universe': self.universe,
            'address': self.address,
            'endAddress': self.end_address,
            'type': self.type,
            'channelCount': self.channel_count,
            'location': self.location,
            'wattage': self.wattage,
            'weight': self.weight,
            'notes': self.notes,
            'firmware': self.firmware,
        }

    
class LabelTemplate(db.Model):
    __tablename__ = 'label_templates'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    config_json = db.Column(db.JSON,   nullable=False)

    def __repr__(self):
        return f"<LabelTemplate {self.name!r}>"


from datetime import datetime, timezone


def _utc_iso(dt):
    """Serialize a naive-UTC column as an UNAMBIGUOUS UTC instant.

    The datetime columns here are filled by `datetime.utcnow()`, so they hold
    UTC with no tzinfo attached. A bare `.isoformat()` renders that as
    "2026-07-21T20:57:05" — no offset — and per the ECMAScript spec a
    date-time string without an offset is parsed as LOCAL time. The browser
    therefore read every timestamp as being `utcoffset` hours in the future
    (4h here), `isOnline` computed a NEGATIVE elapsed time, and
    `negative < 90_000` is always true — so every device showed permanently
    online and "remove offline devices" never found anything to remove.

    Emits a trailing `Z`, which both `new Date()` and `datetime.fromisoformat`
    accept. Values that already carry a tzinfo are converted rather than
    stamped, so this stays correct if a column ever becomes tz-aware.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

class NetworkSubnet(db.Model):
    __tablename__ = 'network_subnets'
    id             = db.Column(db.Integer, primary_key=True)
    label          = db.Column(db.String(100), nullable=False)
    cidr           = db.Column(db.String(50), nullable=False)
    interface_hint = db.Column(db.String(50), nullable=True)
    color          = db.Column(db.String(20), nullable=False, default='#7dd3fc')
    active         = db.Column(db.Boolean, nullable=False, default=True)
    # Comma-separated CIDRs inside `cidr` whose addresses are never persisted
    # as devices. The venue Wi-Fi /23 sits inside the Management /16 and its
    # clients are consumer singletons no OUI table can catch — the subnet
    # boundary is the only thing that separates them from lighting gear.
    ignore_cidrs   = db.Column(db.String(255), nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'cidr': self.cidr,
            'interfaceHint': self.interface_hint,
            'color': self.color,
            'active': self.active,
            'ignoreCidrs': self.ignore_cidrs,
        }


class NetworkDevice(db.Model):
    __tablename__ = 'network_devices'
    mac_address = db.Column(db.String(17), primary_key=True)
    label       = db.Column(db.String(100), nullable=True)
    device_type = db.Column(db.String(50), nullable=False, default='unknown')
    subnet_id   = db.Column(db.Integer, db.ForeignKey('network_subnets.id'), nullable=True)
    notes       = db.Column(db.Text, nullable=True)
    last_ip     = db.Column(db.String(15), nullable=True)
    last_seen   = db.Column(db.DateTime, nullable=True)
    vendor_data = db.Column(db.JSON, nullable=True)
    # Soft hide for the per-subnet "remove offline devices" button. Never a
    # delete: the row is keyed on MAC, so hiding it and un-hiding it on the
    # next sighting is what lets a device come back with its label and notes.
    hidden      = db.Column(db.Boolean, nullable=False, default=False,
                            server_default='0')
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'macAddress': self.mac_address,
            'label': self.label,
            'deviceType': self.device_type,
            'subnetId': self.subnet_id,
            'notes': self.notes,
            'lastIp': self.last_ip,
            'lastSeen': _utc_iso(self.last_seen),
            'vendorData': self.vendor_data,
            'hidden': bool(self.hidden),
            'createdAt': _utc_iso(self.created_at),
        }


class LocationSnapshot(db.Model):
    __tablename__ = 'location_snapshots'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    devices    = db.relationship('LocationDevice', back_populates='snapshot', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'createdAt': _utc_iso(self.created_at),
            'deviceCount': len(self.devices),
        }


class LocationDevice(db.Model):
    __tablename__ = 'location_devices'
    id                  = db.Column(db.Integer, primary_key=True)
    location_id         = db.Column(db.Integer, db.ForeignKey('location_snapshots.id'), nullable=False)
    mac_address         = db.Column(db.String(17), nullable=False)
    ip_at_time          = db.Column(db.String(15), nullable=True)
    online_at_time      = db.Column(db.Boolean, nullable=False, default=True)
    vendor_data_at_time = db.Column(db.JSON, nullable=True)
    snapshot            = db.relationship('LocationSnapshot', back_populates='devices')

    def to_dict(self):
        return {
            'id': self.id,
            'macAddress': self.mac_address,
            'ipAtTime': self.ip_at_time,
            'onlineAtTime': self.online_at_time,
            'vendorDataAtTime': self.vendor_data_at_time,
        }