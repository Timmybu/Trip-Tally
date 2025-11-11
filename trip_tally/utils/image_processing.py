import cv2
import numpy as np
from typing import Tuple


def order_points(pts: np.ndarray) -> np.ndarray:
	"""Return points ordered as top-left, top-right, bottom-right, bottom-left.

	Args:
		pts: Array of four points (x, y).

	Returns:
		Ordered points as np.ndarray of shape (4, 2).
	"""
	if pts.shape[0] != 4:
		raise ValueError("order_points expects 4 points")

	rect = np.zeros((4, 2), dtype="float32")
	# Sum and diff across points
	s = pts.sum(axis=1)
	d = np.diff(pts, axis=1)

	rect[0] = pts[np.argmin(s)]  # top-left has smallest sum
	rect[2] = pts[np.argmax(s)]  # bottom-right has largest sum
	rect[1] = pts[np.argmin(d)]  # top-right has smallest diff
	rect[3] = pts[np.argmax(d)]  # bottom-left has largest diff
	return rect


def four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
	"""Apply perspective transform to obtain a top-down view of the document.

	Args:
		image: Input BGR image
		pts: The four corner points of the document

	Returns:
		Warped (top-down) image
	"""
	rect = order_points(pts)
	(tl, tr, br, bl) = rect

	# Compute width and height of the new image
	widthA = np.linalg.norm(br - bl)
	widthB = np.linalg.norm(tr - tl)
	maxWidth = int(max(widthA, widthB))
	
	heightA = np.linalg.norm(tr - br)
	heightB = np.linalg.norm(tl - bl)
	maxHeight = int(max(heightA, heightB))

	dst = np.array([
		[0, 0],
		[maxWidth - 1, 0],
		[maxWidth - 1, maxHeight - 1],
		[0, maxHeight - 1]
	], dtype="float32")

	M = cv2.getPerspectiveTransform(rect, dst)
	warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
	return warped


def _find_document_contour(edged: np.ndarray) -> np.ndarray:
	"""Find the largest 4-point contour that likely represents the document."""
	contours, _ = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
	contours = sorted(contours, key=cv2.contourArea, reverse=True)
	for c in contours:
		peri = cv2.arcLength(c, True)
		approx = cv2.approxPolyDP(c, 0.02 * peri, True)
		if len(approx) == 4:
			return approx.reshape(4, 2)
	return np.array([])


def preprocess_receipt(image_bgr: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
	"""Detect, warp, and preprocess a receipt for OCR.

	Returns a tuple: (warped_bgr, preprocessed_for_ocr)
	"""
	if image_bgr is None or image_bgr.size == 0:
		raise ValueError("Empty image provided")

	# Resize for processing stability (keep ratio)
	height, width = image_bgr.shape[:2]
	max_dim = 1000
	scale = min(max_dim / max(height, width), 1.0)
	resized = image_bgr if scale == 1.0 else cv2.resize(image_bgr, (int(width * scale), int(height * scale)))

	gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
	blur = cv2.GaussianBlur(gray, (5, 5), 0)
	edged = cv2.Canny(blur, 50, 150)

	# Dilate then erode to close gaps
	kernel = np.ones((3, 3), np.uint8)
	edged = cv2.dilate(edged, kernel, iterations=1)
	edged = cv2.erode(edged, kernel, iterations=1)

	doc_pts = _find_document_contour(edged)
	if doc_pts.size == 0:
		# Fallback: use whole image rectangle
		h, w = resized.shape[:2]
		doc_pts = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)

	# Map points back to original scale if resized
	if scale != 1.0:
		doc_pts = (doc_pts.astype(np.float32) / scale).astype(np.float32)

	warped = four_point_transform(image_bgr, doc_pts.astype(np.float32))
	warped_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)

	# Adaptive threshold improves OCR robustness across lighting
	thresh = cv2.adaptiveThreshold(
		warped_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
	)

	return warped, thresh


