import base64
import io
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from config import Config, allowed_file
from utils.image_processing import preprocess_receipt
from utils.ocr_processor import extract_receipt_data


def get_db_connection(db_path: str):
	conn = sqlite3.connect(db_path)
	conn.row_factory = sqlite3.Row
	return conn


def init_db(db_path: str):
	conn = get_db_connection(db_path)
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
			created_at TEXT
		);
		"""
	)
	conn.commit()
	conn.close()


def create_app() -> Flask:
	app = Flask(__name__, static_folder="static", template_folder="templates")
	config = Config.from_env()
	app.config["SECRET_KEY"] = config.SECRET_KEY
	app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
	app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
	
	# Store config in app for later use
	app.config_obj = config

	# Ensure upload path exists
	upload_path = Path(app.root_path) / app.config["UPLOAD_FOLDER"]
	upload_path.mkdir(parents=True, exist_ok=True)

	# Init DB
	db_path = str(Path(app.root_path) / config.DATABASE_PATH)
	init_db(db_path)

	@app.route("/")
	def index():
		return render_template("index.html")

	@app.route("/upload")
	def upload_page():
		return render_template("upload.html")

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
		conn = get_db_connection(db_path)
		conn.execute(
			"INSERT INTO receipts (filename, merchant, date, total, tax, items, raw_text, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
			(
				filename,
				data.get("merchant", ""),
				data.get("date", ""),
				float(data.get("total") or 0),
				float(data.get("tax") or 0),
				str(data.get("items") or []),
				data.get("raw_text", ""),
				datetime.utcnow().isoformat(),
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
	def uploaded_file(filename):
		return send_from_directory(upload_path, filename)

	return app


app = create_app()

if __name__ == "__main__":
	app.run(debug=True)


