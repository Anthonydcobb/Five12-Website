from flask import (
    Blueprint, render_template, redirect, url_for, request, flash, jsonify,
    send_from_directory, current_app
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app import login_manager, db  # ✅ Import ONLY login_manager and db, NOT app!
from app.models import User, Show, Patch, Fixture, PatchFixture
import os

# ✅ Define Blueprint for main routes
main_bp = Blueprint("main", __name__)

# ---------------------------------------------------
# 🔹 USER AUTHENTICATION ROUTES
# ---------------------------------------------------

@login_manager.user_loader
def load_user(user_id):
    """ Load user for Flask-Login """
    return User.query.get(int(user_id))

@main_bp.route('/register', methods=['GET', 'POST'])
def register():
    """ Render the registration page """
    return render_template("register.html")

@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    """ Handle user login """
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
    """ Logout user and redirect to login """
    logout_user()
    flash('✅ Logged out successfully.', 'info')
    return redirect(url_for('main.login'))

@main_bp.route('/pending_users')
@login_required
def pending_users():
    """ Display list of pending users (Admin Only) """
    if not current_user.is_admin:
        flash("❌ Unauthorized access!", "danger")
        return redirect(url_for('main.home'))

    pending_users = User.query.filter_by(is_approved=False).all()
    return render_template('pending_users.html', pending_users=pending_users)

# ---------------------------------------------------
# 🔹 GENERAL ROUTES
# ---------------------------------------------------

@main_bp.route('/')
def home():
    """ Render the home page """
    return render_template('home.html', current_user=current_user)

@main_bp.route('/favicon.ico')
def favicon():
    """ Serve the favicon """
    return send_from_directory(os.path.join(current_app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

@main_bp.route('/inventory')
@login_required
def inventory():
    """ Render the inventory page """
    return render_template('inventory.html')

# ---------------------------------------------------
# 🔹 SHOW MANAGEMENT ROUTES
# ---------------------------------------------------

@main_bp.route('/shows')
@login_required
def shows():
    """ Display all shows """
    all_shows = Show.query.all()
    return render_template('shows.html', shows=all_shows)

@main_bp.route('/create_show', methods=['POST'])
@login_required
def create_show():
    """ Create a new show """
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
    """ Display show details and its patches """
    show = Show.query.get_or_404(show_id)
    patches = Patch.query.filter_by(show_id=show_id).all()
    return render_template('show_detail.html', show=show, patches=patches)

@main_bp.route('/edit_show/<int:show_id>', methods=['POST'])
@login_required
def edit_show(show_id):
    """ Edit a show (Admin Only) """
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
    """ Delete a show (Admin Only) """
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    show = Show.query.get_or_404(show_id)
    db.session.delete(show)
    db.session.commit()

    return jsonify({"success": True})

# ---------------------------------------------------
# 🔹 PATCH MANAGEMENT ROUTES
# ---------------------------------------------------

@main_bp.route('/patch/<int:patch_id>')
@login_required
def edit_patch(patch_id):
    """ Render the patch editing page """
    patch = Patch.query.get_or_404(patch_id)
    return render_template('patch.html', patch=patch)

@main_bp.route('/create_patch/<int:show_id>', methods=['POST'])
@login_required
def create_patch(show_id):
    """ Create a new patch (Admin Only) """
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

@main_bp.route("/get_patch_fixtures/<int:patch_id>")
def get_patch_fixtures(patch_id):
    """ Retrieve all fixtures for a given patch """
    patch_fixtures = PatchFixture.query.filter_by(patch_id=patch_id).all()

    fixtures = [
        {
            "id": pf.fixture.id,
            "name": pf.fixture.fixture_type,
            "mode": pf.fixture.mode,
            "dmx": f"{pf.fixture.channel_count}ch",
            "wattage": pf.wattage,
            "weight": pf.weight,
            "firmware": pf.firmware,
            "notes": pf.notes
        }
        for pf in patch_fixtures
    ]

    return jsonify(fixtures)

# ---------------------------------------------------
# 🔹 FIXTURE MANAGEMENT ROUTES
# ---------------------------------------------------

@main_bp.route('/add_fixture_to_patch/<int:patch_id>', methods=['POST'])
@login_required
def add_fixture_to_patch(patch_id):
    """ Add selected fixtures to a patch (Admin Only) """
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

@main_bp.route("/get_fixtures", methods=["GET"])
def get_fixtures():
    """ Retrieve all available fixtures """
    try:
        fixtures = Fixture.query.all()
        fixture_data = [
            {
                "id": fixture.id,
                "manufacturer": fixture.manufacturer,
                "name": fixture.fixture_type,
                "mode": fixture.mode if fixture.mode else "—",
                "channel_count": f"{fixture.channel_count}ch" if fixture.channel_count else "—"
            }
            for fixture in fixtures
        ]
        return jsonify(fixture_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500




@main_bp.route("/save_patch_fixtures", methods=["POST"])
def save_patch_fixtures():
    data = request.json  # Receive JSON from frontend
    patch_id = data.get("patch_id")
    fixtures = data.get("fixtures", [])

    if not patch_id or not fixtures:
        print("❌ ERROR: Missing patch_id or fixtures")
        return jsonify({"error": "Missing patch_id or fixtures"}), 400

    try:
        for fixture in fixtures:
            fixture_name = fixture.get("fixture_name")
            mode = fixture.get("mode")

            # ✅ Get fixture_id from database
            existing_fixture = Fixture.query.filter_by(fixture_type=fixture_name, mode=mode).first()

            if not existing_fixture:
                print(f"❌ ERROR: Fixture '{fixture_name}' with mode '{mode}' not found in database!")
                return jsonify({"error": f"Fixture '{fixture_name}' with mode '{mode}' not found"}), 400

            fixture_id = existing_fixture.id  # ✅ Extract fixture_id

            # ✅ Insert into `patch_fixture`
            new_patch_fixture = PatchFixture(
                patch_id=patch_id,
                fixture_id=fixture_id,  # ✅ FIXED: Now we insert a real fixture_id
                quantity=1,
                wattage=None,
                weight=None,
                firmware=None,
                notes=None
            )
            db.session.add(new_patch_fixture)

        db.session.commit()
        print("✅ Fixtures saved successfully!")
        return jsonify({"message": "Fixtures saved successfully!"}), 200

    except Exception as e:
        db.session.rollback()
        print(f"❌ ERROR saving fixtures: {e}")
        return jsonify({"error": "Failed to save fixtures"}), 500












@main_bp.route('/edit_fixtures', methods=['GET'])
@login_required
def edit_fixtures():
    if not current_user.is_admin:
        flash("❌ Unauthorized access!", "danger")
        return redirect(url_for('main.shows'))

    fixtures = Fixture.query.all()
    return render_template('edit_fixtures.html', fixtures=fixtures)


