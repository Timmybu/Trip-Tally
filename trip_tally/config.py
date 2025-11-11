import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def load_env():
	# Load .env from project root if present
	root = Path(__file__).resolve().parent
	load_dotenv(dotenv_path=root / ".env")


@dataclass
class Config:
	SECRET_KEY: str
	UPLOAD_FOLDER: str
	DATABASE_PATH: str
	AZURE_CV_ENDPOINT: str
	AZURE_CV_KEY: str
	MAX_CONTENT_LENGTH: int = 20 * 1024 * 1024  # 20MB

	@classmethod
	def from_env(cls) -> "Config":
		load_env()
		secret = os.getenv("FLASK_SECRET_KEY") or os.urandom(24).hex()
		upload = os.getenv("UPLOAD_FOLDER", "static/uploads")
		db_path = os.getenv("DATABASE_PATH", "trip_tally.db")
		endpoint = os.getenv("AZURE_CV_ENDPOINT", "")
		key = os.getenv("AZURE_CV_KEY", "")
		return cls(
			SECRET_KEY=secret,
			UPLOAD_FOLDER=upload,
			DATABASE_PATH=db_path,
			AZURE_CV_ENDPOINT=endpoint,
			AZURE_CV_KEY=key,
		)


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}

def allowed_file(filename: str) -> bool:
	return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


