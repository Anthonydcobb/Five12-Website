from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager
from app.models import User, Show, Patch, Fixture, db, PatchFixture

# ✅ Define Blueprint
main_bp = Blueprint("main", __name__)

# ✅ Flask-Login User Loader
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))



@main_bp.route('/inventory')
@login_required
def inventory():
    return render_template('inventory.html')

@main_bp.route('/edit_fixtures', methods=['GET'])
@login_required
def edit_fixtures():
    if not current_user.is_admin:
        flash("❌ Unauthorized access!", "danger")
        return redirect(url_for('main.shows'))

    fixtures = Fixture.query.all()
    return render_template('edit_fixtures.html', fixtures=fixtures)


# --------------------- USERS AND AUTH ---------------------

@main_bp.route('/')
def home():
    return render_template('home.html', current_user=current_user)

@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('✅ Login successful!', 'success')
            return redirect(url_for('main.home'))
        else:
            flash('❌ Invalid username or password.', 'danger')

    return render_template('login.html')

@main_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('✅ Logged out successfully.', 'info')
    return redirect(url_for('main.login'))

@main_bp.route('/pending_users')
@login_required
def pending_users():
    if not current_user.is_admin:
        flash("❌ Unauthorized access!", "danger")
        return redirect(url_for('main.home'))

    pending_users = User.query.filter_by(is_approved=False).all()
    return render_template('pending_users.html', pending_users=pending_users)





# --------------------- SHOWS ---------------------

@main_bp.route('/shows')
@login_required
def shows():
    all_shows = Show.query.all()
    return render_template('shows.html', shows=all_shows)

@main_bp.route('/create_show', methods=['POST'])
@login_required
def create_show():
    show_name = request.form.get('show_name')
    if show_name:
        new_show = Show(name=show_name)
        db.session.add(new_show)
        db.session.commit()
        return redirect(url_for('main.shows'))
    return "Error: Show name is required", 400

@main_bp.route('/show/<int:show_id>')
@login_required
def show_detail(show_id):
    show = Show.query.get_or_404(show_id)
    patches = Patch.query.filter_by(show_id=show_id).all()
    return render_template('show_detail.html', show=show, patches=patches)

@main_bp.route('/edit_show/<int:show_id>', methods=['POST'])
@login_required
def edit_show(show_id):
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    data = request.get_json()
    show = Show.query.get_or_404(show_id)
    show.name = data.get("name", show.name)
    db.session.commit()

    return jsonify({"success": True})

@main_bp.route('/delete_show/<int:show_id>', methods=['POST'])
@login_required
def delete_show(show_id):
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    show = Show.query.get_or_404(show_id)
    db.session.delete(show)
    db.session.commit()

    return jsonify({"success": True})

# --------------------- PATCHES ---------------------

### ✅ FIXED: CREATE PATCH (Uses JSON instead of `request.form.get()`)
@main_bp.route('/create_patch/<int:show_id>', methods=['POST'])
@login_required
def create_patch(show_id):
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    data = request.get_json()
    patch_name = data.get("name", "").strip()  # Extract JSON data correctly

    if not patch_name:
        return jsonify({"success": False, "error": "Patch name is required"}), 400

    new_patch = Patch(name=patch_name, show_id=show_id)
    db.session.add(new_patch)
    db.session.commit()

    return jsonify({"success": True})  # Return success for frontend JS

### ✅ FIXED: EDIT PATCH (Ensures correct template rendering)
@main_bp.route('/patch/<int:patch_id>')
@login_required
def edit_patch(patch_id):
    patch = Patch.query.get_or_404(patch_id)
    return render_template('patch.html', patch=patch)

### ✅ FIXED: UPDATE PATCH (Prevents 405 Method Not Allowed)
@main_bp.route('/update_patch/<int:patch_id>', methods=['POST'])
@login_required
def update_patch(patch_id):
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    data = request.get_json()
    patch = Patch.query.get_or_404(patch_id)

    patch_name = data.get("name", "").strip()
    if not patch_name:
        return jsonify({"success": False, "error": "Patch name cannot be empty"}), 400

    patch.name = patch_name
    db.session.commit()

    return jsonify({"success": True})

### ✅ FIXED: DELETE PATCH
@main_bp.route('/delete_patch/<int:patch_id>', methods=['POST'])
@login_required
def delete_patch(patch_id):
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    patch = Patch.query.get_or_404(patch_id)
    db.session.delete(patch)
    db.session.commit()

    return jsonify({"success": True})

### ✅ FIXED: ADD PATCH (Ensures correct JSON handling)
@main_bp.route('/add_patch/<int:show_id>', methods=['POST'])
@login_required
def add_patch(show_id):
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    data = request.get_json()
    patch_name = data.get("name", "").strip()

    if not patch_name:
        return jsonify({"success": False, "error": "Patch name is required"}), 400

    new_patch = Patch(name=patch_name, show_id=show_id)
    db.session.add(new_patch)
    db.session.commit()

    return jsonify({"success": True})


@main_bp.route('/add_fixture_to_patch/<int:patch_id>', methods=['POST'])
@login_required
def add_fixture_to_patch(patch_id):
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    patch = Patch.query.get_or_404(patch_id)
    data = request.get_json()
    fixtures = data.get("fixtures", [])

    if not fixtures:
        return jsonify({"success": False, "error": "No fixtures selected"}), 400

    for fixture in fixtures:
        new_entry = PatchFixture(
            patch_id=patch.id,
            fixture_id=fixture["id"],
            quantity=fixture["qty"]
        )
        db.session.add(new_entry)

    db.session.commit()
    return jsonify({"success": True})

@main_bp.route('/add_fixture', methods=['POST'])
@login_required
def add_fixture():
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Invalid JSON data"}), 400

        manufacturer = data.get("manufacturer", "").strip()
        fixture_type = data.get("fixture_type", "").strip()
        mode = data.get("mode", "").strip()
        channel_count = int(data.get("channel_count")) if data.get("channel_count") else None
        wattage = int(data.get("wattage")) if data.get("wattage") else None
        weight = float(data.get("weight")) if data.get("weight") else None
        firmware = data.get("firmware", "").strip() or None
        notes = data.get("notes", "").strip() or None

        # ✅ Ensure required fields are present
        if not manufacturer or not fixture_type or not mode or not channel_count:
            return jsonify({"success": False, "error": "Missing required fields"}), 400

        # ✅ Create and save the fixture
        new_fixture = Fixture(
            manufacturer=manufacturer,
            fixture_type=fixture_type,
            mode=mode,
            channel_count=channel_count,
            wattage=wattage,
            weight=weight,
            firmware=firmware,
            notes=notes
        )
        db.session.add(new_fixture)
        db.session.commit()

        # ✅ Return full fixture data
        return jsonify({
            "success": True,
            "fixture": {
                "id": new_fixture.id,
                "manufacturer": new_fixture.manufacturer,
                "fixture_type": new_fixture.fixture_type,
                "mode": new_fixture.mode,
                "channel_count": new_fixture.channel_count,
                "wattage": new_fixture.wattage,
                "weight": new_fixture.weight,
                "firmware": new_fixture.firmware,
                "notes": new_fixture.notes
            }
        })

    except Exception as e:
        print("❌ Error in add_fixture:", e)  # ✅ Log error for debugging
        return jsonify({"success": False, "error": str(e)}), 500  # ✅ Return JSON error response




@main_bp.route('/delete_fixtures', methods=['POST'])
@login_required
def delete_fixtures():
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    try:
        data = request.get_json()
        fixture_ids = data.get("fixture_ids", [])

        if not fixture_ids:
            return jsonify({"success": False, "error": "No fixture IDs provided"}), 400

        # ✅ Ensure all IDs are integers
        fixture_ids = [int(id) for id in fixture_ids]

        # ✅ Delete fixtures
        db.session.query(Fixture).filter(Fixture.id.in_(fixture_ids)).delete(synchronize_session=False)
        db.session.commit()

        return jsonify({"success": True})

    except Exception as e:
        print(f"❌ Error in delete_fixtures: {e}")  # ✅ Log error for debugging
        return jsonify({"success": False, "error": str(e)}), 500  # ✅ Return JSON error response
