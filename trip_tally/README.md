Trip Tally
===========

A mobile-friendly Flask app for truck drivers to upload receipt images, auto-warp and clean the image with OpenCV, run OCR via Azure Computer Vision, parse basic fields, and store results in SQLite.

Quickstart
----------
1) Create venv and install deps:
```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -r requirements.txt
```

2) Configure environment variables:
- Copy `.env.example` to `.env` and set `AZURE_CV_ENDPOINT` and `AZURE_CV_KEY`.

3) Run the app:
```bash
python app.py
# or
waitress-serve --listen=0.0.0.0:8000 app:app
```

Open http://127.0.0.1:5000/ in your browser.

Environment
-----------
- `FLASK_SECRET_KEY` (optional)
- `AZURE_CV_ENDPOINT`
- `AZURE_CV_KEY`
- `UPLOAD_FOLDER` (default: static/uploads)
- `DATABASE_PATH` (default: trip_tally.db)

Notes
-----
- Uses Azure Read API v3.2 asynchronously, polling operation-location.
- OpenCV pipeline: grayscale → Gaussian blur → Canny edges → contour detect → four-point warp → adaptive threshold.
- Supported image types: jpg, jpeg, png, webp, bmp, tiff.


