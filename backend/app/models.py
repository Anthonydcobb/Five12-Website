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

    