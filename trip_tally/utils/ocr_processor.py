import base64
import json
import os
import re
import time
from typing import Dict, List, Tuple

import requests


class AzureOCRClient:
	def __init__(self, endpoint: str, key: str, api_version: str = "v3.2"):
		self.endpoint = endpoint.rstrip("/")
		self.key = key
		self.api_version = api_version

	def analyze_image_bytes(self, image_bytes: bytes, timeout_seconds: int = 30) -> List[str]:
		"""Send image to Azure Read Analyze and return list of OCR lines when done."""
		url = f"{self.endpoint}/vision/{self.api_version}/read/analyze"
		headers = {
			"Ocp-Apim-Subscription-Key": self.key,
			"Content-Type": "application/octet-stream",
		}
		resp = requests.post(url, headers=headers, data=image_bytes, timeout=timeout_seconds)
		if resp.status_code not in (202, 200):
			raise RuntimeError(f"Azure analyze failed: {resp.status_code} {resp.text}")
		operation_location = resp.headers.get("operation-location")
		if not operation_location:
			raise RuntimeError("No operation-location header returned by Azure Read API")

		# Poll for result
		for _ in range(60):  # up to ~60 * 1s = 60s
			res = requests.get(operation_location, headers={"Ocp-Apim-Subscription-Key": self.key}, timeout=timeout_seconds)
			if res.status_code != 200:
				time.sleep(1)
				continue
			data = res.json()
			status = data.get("status")
			if status == "succeeded":
				lines: List[str] = []
				analyze_result = data.get("analyzeResult", {})
				for read_result in analyze_result.get("readResults", []):
					for line in read_result.get("lines", []):
						text = line.get("text", "").strip()
						if text:
							lines.append(text)
				return lines
			elif status in ("failed", "error"):
				raise RuntimeError("Azure Read operation failed")
			time.sleep(1)
		raise TimeoutError("Azure Read operation timed out")


def parse_receipt_text(lines: List[str]) -> Dict:
	"""Very basic parsing heuristics to extract merchant, date, total, tax, items."""
	joined = "\n".join(lines)

	# Merchant: first non-empty line, excluding common words
	merchant = ""
	for line in lines:
		clean = line.strip()
		if not clean:
			continue
		if re.search(r"(total|visa|mastercard|debit|credit|invoice|receipt)", clean, re.I):
			continue
		merchant = clean
		break

	# Date: attempt multiple formats
	date_patterns = [
		r"\b(\d{4}[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01]))\b",  # YYYY-MM-DD
		r"\b((?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])[-/]\d{2,4})\b",  # MM/DD/YYYY
		r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})\b",
	]
	date = ""
	for pat in date_patterns:
		m = re.search(pat, joined, re.I)
		if m:
			date = m.group(1)
			break

# ... (keep merchant and date logic the same)

	# --- IMPROVED TOTAL EXTRACTION ---
	amount_re = r"\$?\s*([0-9]+(?:\.[0-9]{2})?)"
	
	# Strategy 1: Keyword Search (High Confidence)
	# We look for lines explicitly labeled "Total", "Balance", etc.
	total_keywords = r"\b(total|amount due|balance due|grand total)\b"
	line_with_total = next((l for l in lines if re.search(total_keywords, l, re.I)), "")
	
	def extract_amount(line: str) -> float:
		m = re.search(amount_re, line)
		if m:
			try:
				return float(m.group(1))
			except ValueError:
				return 0.0
		return 0.0

	total_val = extract_amount(line_with_total)

	# Strategy 2: Largest Dollar Amount (Fallback)
	# If Strategy 1 failed (total_val is 0), find the largest number preceded by a '$'
	if total_val == 0.0:
		all_dollar_values = []
		# Regex requiring a '$' sign to be safe
		strict_dollar_re = r"\$\s*([0-9]+\.[0-9]{2})"
		
		for line in lines:
			# Find all matches in the line (in case multiple prices are on one line)
			matches = re.findall(strict_dollar_re, line)
			for m in matches:
				try:
					all_dollar_values.append(float(m))
				except ValueError:
					continue
		
		if all_dollar_values:
			total_val = max(all_dollar_values)

	# Convert back to string for consistency with your data structure, or keep as float
	total = str(total_val) if total_val > 0 else ""
	
	# Tax Logic (Keep existing)
	line_with_tax = next((l for l in lines if re.search(r"\b(tax|hst|gst|vat)\b", l, re.I)), "")
	tax = str(extract_amount(line_with_tax)) if line_with_tax else ""

	# ... (Rest of function)

	# Items: heuristic - lines between merchant and total that look like item descriptions with an amount
	items: List[Tuple[str, str]] = []
	if merchant and line_with_total:
		try:
			start_idx = lines.index(merchant)
		except ValueError:
			start_idx = 0
		end_idx = lines.index(line_with_total) if line_with_total in lines else len(lines)
		for l in lines[start_idx + 1:end_idx]:
			m = re.search(amount_re, l)
			if m and not re.search(r"\b(total|tax)\b", l, re.I):
				items.append((l.strip(), m.group(1)))

	return {
		"merchant": merchant,
		"date": date,
		"total": total,
		"tax": tax,
		"items": items,
		"raw_text": joined,
	}


def extract_receipt_data(image_bytes: bytes, endpoint: str, key: str) -> Dict:
	client = AzureOCRClient(endpoint, key)
	lines = client.analyze_image_bytes(image_bytes)
	data = parse_receipt_text(lines)
	return data


