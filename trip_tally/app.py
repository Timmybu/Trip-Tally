import base64
import io
import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import UserMixin, LoginManager, login_required, current_user, login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from config import Config, allowed_file
from utils.image_processing import preprocess_receipt
from utils.ocr_processor import extract_receipt_data


# Global variable to store db_path (will be set in create_app)
db_path = None
login_manager = LoginManager()


class User(UserMixin):
	def __init__(self, id, username, role):
		self.id = id
		self.username = username
		self.role = role


@login_manager.user_loader
def load_user(user_id):
	if db_path is None:
		return None
	conn = get_db_connection(db_path)
	user_row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
	conn.close()
	if user_row:
		return User(id=user_row['id'], username=user_row['username'], role=user_row['role'])
	return None


def get_db_connection(db_path: str):
	conn = sqlite3.connect(db_path)
	conn.row_factory = sqlite3.Row
	return conn


def init_db(db_path: str):
	conn = get_db_connection(db_path)
	# Create users table
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS users (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			username TEXT NOT NULL UNIQUE,
			password_hash TEXT NOT NULL,
			role TEXT NOT NULL DEFAULT 'driver'
		);
		"""
	)
	# Create trips table
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS trips (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			name TEXT NOT NULL,
			user_id INTEGER,
			FOREIGN KEY (user_id) REFERENCES users(id)
		);
		"""
	)
	# Create receipts table
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS receipts (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			filename TEXT,
			merchant TEXT,
			date TEXT,
			total REAL,
			tax REAL,
			items TEXT,
			raw_text TEXT,
			created_at TEXT,
			trip_id INTEGER,
			user_id INTEGER,
			FOREIGN KEY (trip_id) REFERENCES trips(id),
			FOREIGN KEY (user_id) REFERENCES users(id)
		);
		"""
	)
	# Add trip_id column to existing receipts table if it doesn't exist
	try:
		conn.execute("ALTER TABLE receipts ADD COLUMN trip_id INTEGER")
		conn.commit()
	except sqlite3.OperationalError:
		# Column already exists, ignore
		pass
	# Add user_id column to existing trips table if it doesn't exist
	try:
		conn.execute("ALTER TABLE trips ADD COLUMN user_id INTEGER")
		conn.commit()
	except sqlite3.OperationalError:
		# Column already exists, ignore
		pass
	# Add user_id column to existing receipts table if it doesn't exist
	try:
		conn.execute("ALTER TABLE receipts ADD COLUMN user_id INTEGER")
		conn.commit()
	except sqlite3.OperationalError:
		# Column already exists, ignore
		pass
	conn.commit()
	conn.close()


def create_app() -> Flask:
	global db_path
	app = Flask(__name__, static_folder="static", template_folder="templates")
	config = Config.from_env()
	app.config["SECRET_KEY"] = config.SECRET_KEY
	app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
	app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
	
	# Store config in app for later use
	app.config_obj = config

	# Initialize LoginManager
	login_manager.init_app(app)
	login_manager.login_view = 'login'

	# Ensure upload path exists
	upload_path = Path(app.root_path) / app.config["UPLOAD_FOLDER"]
	upload_path.mkdir(parents=True, exist_ok=True)

	# Init DB
	db_path = str(Path(app.root_path) / config.DATABASE_PATH)
	init_db(db_path)

	def admin_required(f):
		@wraps(f)
		def decorated_function(*args, **kwargs):
			if not current_user.is_authenticated or current_user.role != 'admin':
				flash("You do not have permission to access this page.", "error")
				return redirect(url_for('index'))
			return f(*args, **kwargs)
		return decorated_function

	@app.route("/")
	def index():
		return render_template("index.html")

	@app.route("/register", methods=["GET", "POST"])
	def register():
		if request.method == "POST":
			username = request.form.get("username", "").strip()
			password = request.form.get("password", "").strip()
			if not username or not password:
				flash("Username and password are required.", "error")
				return redirect(url_for('register'))
			hash = generate_password_hash(password)
			conn = get_db_connection(db_path)
			try:
				conn.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", (username, hash, 'driver'))
				conn.commit()
			except sqlite3.IntegrityError:
				flash("Username already taken.", "error")
				conn.close()
				return redirect(url_for('register'))
			conn.close()
			flash("Account created, please login.", "success")
			return redirect(url_for("login"))
		return render_template("register.html")

	@app.route("/login", methods=["GET", "POST"])
	def login():
		if request.method == "POST":
			username = request.form.get("username", "").strip()
			password = request.form.get("password", "").strip()
			conn = get_db_connection(db_path)
			user_row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
			conn.close()
			if user_row and check_password_hash(user_row['password_hash'], password):
				user = User(id=user_row['id'], username=user_row['username'], role=user_row['role'])
				login_user(user)
				return redirect(url_for('index'))
			flash("Invalid username or password.", "error")
		return render_template("login.html")

	@app.route("/logout")
	@login_required
	def logout():
		logout_user()
		return redirect(url_for("index"))

	@app.route("/upload")
	@login_required
	def upload_page():
		"""Display upload page with trip selection"""
		conn = get_db_connection(db_path)
		trips = conn.execute("SELECT id, name FROM trips WHERE user_id = ? ORDER BY name", (current_user.id,)).fetchall()
		conn.close()
		return render_template("upload.html", trips=trips)

	@app.route("/history")
	@login_required
	def history():
		"""Display all previously processed receipts"""
		conn = get_db_connection(db_path)
		receipts = conn.execute(
			"""
			SELECT r.id, r.filename, r.merchant, r.date, r.total, r.created_at, r.trip_id,
			       t.name as trip_name
			FROM receipts r
			LEFT JOIN trips t ON r.trip_id = t.id
			WHERE r.user_id = ?
			ORDER BY r.created_at DESC
			""",
			(current_user.id,)
		).fetchall()
		conn.close()
		return render_template("history.html", receipts=receipts)

	# In trip_tally/app.py

	@app.route("/debug")
	def debug_config():
		"""Debug route to check environment variable loading"""

		# --- START DEBUGGING TEST ---
		print("--- !!! THE NEW DEBUG ROUTE WAS CALLED !!! ---")
		return {
			"message": "THE NEW SERVER IS RUNNING!",
			"test_value": "THIS IS PROOF"
		}
		# --- END DEBUGGING TEST ---

		# ... (the old code is below, leave it commented out or deleted for now)
		# config = app.config_obj
		# return {
		# 	"AZURE_CV_ENDPOINT": config.AZURE_CV_ENDPOINT,
		# 	"AZURE_CV_KEY": "***" + config.AZURE_CV_KEY[-4:] if config.AZURE_CV_KEY else "NOT SET",
		# 	"UPLOAD_FOLDER": config.UPLOAD_FOLDER,
		# 	"DATABASE_PATH": config.DATABASE_PATH,
		# }

	@app.post("/upload")
	@login_required
	def handle_upload():
		if "file" not in request.files:
			flash("No file part in the request.", "error")
			return redirect(url_for("upload_page"))
		file = request.files["file"]
		if file.filename == "":
			flash("No selected file.", "error")
			return redirect(url_for("upload_page"))
		if not allowed_file(file.filename):
			flash("Invalid file type.", "error")
			return redirect(url_for("upload_page"))

		filename = secure_filename(file.filename)
		# Read bytes for processing first
		image_bytes = file.read()
		if not image_bytes:
			flash("Empty file uploaded.", "error")
			return redirect(url_for("upload_page"))

		# Save original upload
		original_path = upload_path / filename
		with open(original_path, "wb") as f:
			f.write(image_bytes)

		# Preprocess using OpenCV
		import numpy as np
		import cv2
		np_arr = np.frombuffer(image_bytes, np.uint8)
		img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
		try:
			warped_bgr, preprocessed = preprocess_receipt(img_bgr)
		except Exception as e:
			flash(f"Image processing failed: {e}", "error")
			return redirect(url_for("upload_page"))

		# Encode images for display
		_, warped_jpg = cv2.imencode(".jpg", warped_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
		_, pre_jpg = cv2.imencode(".jpg", preprocessed)
		warped_b64 = base64.b64encode(warped_jpg.tobytes()).decode("ascii")
		pre_b64 = base64.b64encode(pre_jpg.tobytes()).decode("ascii")

		# OCR via Azure
		config = app.config_obj
		if not config.AZURE_CV_ENDPOINT or not config.AZURE_CV_KEY:
			flash("Azure credentials not configured.", "error")
			return redirect(url_for("upload_page"))
		try:
			data = extract_receipt_data(pre_jpg.tobytes(), config.AZURE_CV_ENDPOINT, config.AZURE_CV_KEY)
		except Exception as e:
			flash(f"OCR failed: {e}", "error")
			return redirect(url_for("upload_page"))

		# Store in DB
		trip_id = request.form.get('trip_id')
		trip_id = int(trip_id) if trip_id and trip_id.isdigit() else None
		conn = get_db_connection(db_path)
		conn.execute(
			"INSERT INTO receipts (filename, merchant, date, total, tax, items, raw_text, created_at, trip_id, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
			(
				filename,
				data.get("merchant", ""),
				data.get("date", ""),
				float(data.get("total") or 0),
				float(data.get("tax") or 0),
				str(data.get("items") or []),
				data.get("raw_text", ""),
				datetime.utcnow().isoformat(),
				trip_id,
				current_user.id,
			),
		)
		conn.commit()
		conn.close()

		return render_template(
			"results.html",
			filename=filename,
			warped_b64=warped_b64,
			pre_b64=pre_b64,
			data=data,
		)

	@app.get("/uploads/<path:filename>")
	@login_required
	def uploaded_file(filename):
		return send_from_directory(upload_path, filename)

	@app.route("/trips", methods=["GET"])
	@login_required
	def trips():
		"""Display trips management page"""
		conn = get_db_connection(db_path)
		trips_list = conn.execute("SELECT id, name FROM trips WHERE user_id = ? ORDER BY name", (current_user.id,)).fetchall()
		conn.close()
		return render_template("trips.html", trips=trips_list)

	@app.route("/trips", methods=["POST"])
	@login_required
	def create_trip():
		"""Create a new trip"""
		name = request.form.get("name", "").strip()
		if not name:
			flash("Trip name cannot be empty.", "error")
			return redirect(url_for("trips"))
		conn = get_db_connection(db_path)
		conn.execute("INSERT INTO trips (name, user_id) VALUES (?, ?)", (name, current_user.id))
		conn.commit()
		conn.close()
		flash(f"Trip '{name}' created successfully.", "success")
		return redirect(url_for("trips"))

	@app.route("/edit/<int:id>", methods=["GET"])
	@login_required
	def edit_receipt(id):
		"""Display edit receipt form"""
		conn = get_db_connection(db_path)
		receipt = conn.execute(
			"SELECT * FROM receipts WHERE id = ? AND user_id = ?", (id, current_user.id)
		).fetchone()
		if not receipt:
			flash("Receipt not found or you don't have permission to edit it.", "error")
			conn.close()
			return redirect(url_for("history"))
		trips_list = conn.execute("SELECT id, name FROM trips WHERE user_id = ? ORDER BY name", (current_user.id,)).fetchall()
		conn.close()
		return render_template("edit_receipt.html", receipt=receipt, trips=trips_list)

	@app.route("/edit/<int:id>", methods=["POST"])
	@login_required
	def update_receipt(id):
		"""Update a receipt"""
		merchant = request.form.get("merchant", "").strip()
		date = request.form.get("date", "").strip()
		total = request.form.get("total", "0").strip()
		tax = request.form.get("tax", "0").strip()
		trip_id = request.form.get("trip_id", "").strip()
		
		try:
			total = float(total) if total else 0.0
			tax = float(tax) if tax else 0.0
			trip_id = int(trip_id) if trip_id and trip_id.isdigit() else None
		except ValueError:
			flash("Invalid numeric values.", "error")
			return redirect(url_for("edit_receipt", id=id))
		
		conn = get_db_connection(db_path)
		conn.execute(
			"UPDATE receipts SET merchant = ?, date = ?, total = ?, tax = ?, trip_id = ? WHERE id = ? AND user_id = ?",
			(merchant, date, total, tax, trip_id, id, current_user.id)
		)
		conn.commit()
		conn.close()
		flash("Receipt updated successfully.", "success")
		return redirect(url_for("history"))

	@app.route("/delete/<int:id>", methods=["POST"])
	@login_required
	def delete_receipt(id):
		"""Delete a receipt"""
		conn = get_db_connection(db_path)
		conn.execute("DELETE FROM receipts WHERE id = ? AND user_id = ?", (id, current_user.id))
		conn.commit()
		conn.close()
		flash("Receipt deleted successfully.", "success")
		return redirect(url_for("history"))

	@app.route("/admin/all_uploads")
	@login_required
	@admin_required
	def admin_all_uploads():
		"""Admin view of all receipts from all users"""
		conn = get_db_connection(db_path)
		all_receipts = conn.execute(
			"""
			SELECT r.*, u.username, t.name as trip_name
			FROM receipts r
			LEFT JOIN users u ON r.user_id = u.id
			LEFT JOIN trips t ON r.trip_id = t.id
			ORDER BY r.created_at DESC
			"""
		).fetchall()
		conn.close()
		return render_template("admin_view.html", receipts=all_receipts)

	return app


app = create_app()

if __name__ == "__main__":
	app.run(debug=True)


