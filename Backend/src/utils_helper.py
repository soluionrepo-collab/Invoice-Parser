import time
import io
import json
import os
import fitz
import base64
import hashlib
from PIL import Image
from src.adapters.logger import logger
from typing import List, Dict, Any
from pathlib import Path


def time_it(func):
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        print(f"[TIME] {func.__name__} took {(end - start):.3f} seconds")
        return result
    return wrapper

@time_it
def b64_image_highres(path_or_image, scale=2):
    """Convert image path or PIL.Image to base64 after scaling."""
    if isinstance(path_or_image, str):  # path case
        img = Image.open(path_or_image)
    else:  # already a PIL.Image
        img = path_or_image

    new_size = (img.width * scale, img.height * scale)
    img = img.resize(new_size, Image.LANCZOS)

    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

@time_it
def extract_image_content(file_path):
    """
    Accepts a single file path (image or pdf).
    Returns the single image content dict ready to send to the model.
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        img = pdf_to_image_first_page_fitz(file_path) 
        b64_str = b64_image_highres(img, scale=2)
    else:
        b64_str = b64_image_highres(file_path, scale=2)

    image_content = {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{b64_str}"}
    }
    return image_content

def pdf_to_image_first_page_fitz(pdf_path_or_bytes, dpi=100):
    """Convert PDF to PIL Image using PyMuPDF (fitz) - kept synchronous for thread pool execution."""
    
    try:
        # Open PDF document
        if isinstance(pdf_path_or_bytes, str):
            # File path
            doc = fitz.open(pdf_path_or_bytes)
        else:
            # Bytes
            doc = fitz.open(stream=pdf_path_or_bytes, filetype="pdf")
        
        if len(doc) == 0:
            raise ValueError("PDF has no pages")
        
        # Get first page
        page = doc[0]
        
        # Calculate matrix for desired DPI
        # Default DPI in fitz is 72, so we scale accordingly
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        
        # Render page to pixmap
        pix = page.get_pixmap(matrix=mat)
        
        # Convert pixmap to PIL Image
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))
        
        # Clean up
        doc.close()
        return img
        
    except Exception as e:
        logger.error(f"PDF to image conversion failed: {e}")
        raise

def decode_json(text):
    """
    Decodes multiple JSON objects from a string and returns the first one.
    """
    try:
        decoder = json.JSONDecoder()
        pos = 0
        json_objects = []
        while pos < len(text):
            try:
                obj, pos = decoder.raw_decode(text, pos)
                json_objects.append(obj)
            except Exception:
                pos += 1
        return json_objects[0]
    except Exception as e:
        logger.critical(f"Critical error in decode_json function: {e}")
        return {"system": "Critical error received"}

def polygon_to_pairs(poly):
    """
    Normalize many possible polygon formats to [[x,y], [x,y], ...].
    """
    if not poly:
        return []

    out = []

    try:
        first = poly[0]
    except Exception:
        return []

    if hasattr(first, "x") and hasattr(first, "y"):
        for p in poly:
            out.append([float(p.x), float(p.y)])
        return out

    if isinstance(first, dict) and "x" in first and "y" in first:
        for p in poly:
            out.append([float(p["x"]), float(p["y"])])
        return out

    if isinstance(first, (list, tuple)) and len(first) == 2:
        for p in poly:
            out.append([float(p[0]), float(p[1])])
        return out

    vals = []
    for v in poly:
        if hasattr(v, "x") and hasattr(v, "y"):
            vals.extend([float(v.x), float(v.y)])
        elif isinstance(v, dict) and "x" in v and "y" in v:
            vals.extend([float(v["x"]), float(v["y"])])
        elif isinstance(v, (int, float, str)):
            vals.append(float(v))

    for i in range(0, len(vals) - 1, 2):
        out.append([vals[i], vals[i + 1]])

    return out

def map_polygons_to_llm_output(llm_output: dict, key_to_di: dict) -> dict:
    """
    Improved polygon mapping function with better error handling and logging.
    """
    def map_polygon_recursively(obj, path="root"):
        """Recursively find and map polygon fields in nested structures."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{path}.{key}"
                if key == 'polygon':
                    # This is a polygon field that needs mapping
                    polygon_id = str(value) if value is not None else None
                    if polygon_id and polygon_id in key_to_di:
                        mapped_polygon = key_to_di[polygon_id]['polygon']
                        logger.debug(f"Mapped polygon at {current_path}: {polygon_id} -> {len(mapped_polygon)} points")
                        obj[key] = mapped_polygon
                    else:
                        logger.warning(f"No polygon mapping found at {current_path} for ID: {polygon_id}")
                        obj[key] = []
                else:
                    # Recursively process nested structures
                    map_polygon_recursively(value, current_path)
        elif isinstance(obj, list):
            # Process each item in the list
            for i, item in enumerate(obj):
                map_polygon_recursively(item, f"{path}[{i}]")
    
    try:
        # Create a deep copy to avoid modifying the original
        import copy
        mapped_output = copy.deepcopy(llm_output)
        
        # Apply polygon mapping recursively
        map_polygon_recursively(mapped_output)
        
        return mapped_output
        
    except Exception as e:
        logger.error(f"Error in polygon mapping: {e}", exc_info=True)
        return llm_output

# ---------------- Score + compact helpers (to reduce prompt size) ----------------
def _score_text_candidate(text: str) -> float:
    if not text:
        return 0.0
    s = text.strip()
    if len(s) < 2:
        return 0.0
    chars = len(s)
    digits = sum(1 for c in s if c.isdigit())
    digit_ratio = digits / max(1, chars)
    uppercase = sum(1 for c in s if c.isupper())
    uppercase_ratio = uppercase / max(1, chars)
    token_count = len(s.split())
    sep_count = s.count(":") + s.count("-") + s.count("/") + s.count(",")
    if chars <= 6:
        length_score = 0.2
    elif chars <= 40:
        length_score = 1.0
    elif chars <= 120:
        length_score = 0.8
    else:
        length_score = 0.4
    score = (
        (digit_ratio * 3.0)
        + (sep_count * 0.5)
        + (uppercase_ratio * 0.6)
        + (token_count * 0.2)
        + (length_score * 1.0)
    )
    return score / (1.0 + (chars / 200.0))

def prepare_compact_for_gpt(extracted_items: List[Dict[str, Any]],
                            truncate_chars: int = 60,
                            compact_max_items: int = 60) -> List[Dict[str, Any]]:
    """
    Deduplicate and pick top-scored items, return [{"id": idx, "text": truncated_text}, ...]
    """
    best_map = {}
    for idx, it in enumerate(extracted_items):
        txt = (it.get("text") or "").strip()
        if not txt:
            continue
        score = _score_text_candidate(txt)
        existing = best_map.get(txt)
        if existing is None or score > existing[0]:
            best_map[txt] = (score, idx, txt)

    candidates = list(best_map.values())
    candidates.sort(key=lambda x: (-x[0], x[1]))
    selected = sorted(candidates[:compact_max_items], key=lambda x: x[1])

    compact = []
    for _, idx, txt in selected:
        t = txt if len(txt) <= truncate_chars else (txt[:truncate_chars] + "...")
        compact.append({"id": idx, "text": t})

    # fallback: small set of first distinct items
    if not compact:
        seen = set()
        for idx, it in enumerate(extracted_items):
            txt = (it.get("text") or "").strip()
            if not txt or txt in seen:
                continue
            seen.add(txt)
            t = txt if len(txt) <= truncate_chars else (txt[:truncate_chars] + "...")
            compact.append({"id": idx, "text": t})
            if len(compact) >= min(compact_max_items, 50):
                break

    return compact

ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg"}


async def file_to_pdf_bytes(path: str) -> dict:
    """
    Convert an image file to a single-page PDF bytes, or return PDF bytes for .pdf.
    Returns a dict with keys: "bytes", "width", "height".
    """
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as fh:
        raw = fh.read()

    if ext == ".pdf":
        pdf_doc = fitz.open(stream=raw, filetype="pdf")
        rect = pdf_doc[0].rect
        pdf_doc.close()
        return {"bytes": raw, "width": rect.width, "height": rect.height}

    # For images
    pdf_doc = fitz.open()
    filetype = ext.lstrip(".")
    img_doc = fitz.open(stream=raw, filetype=filetype)
    if len(img_doc) == 0:
        img_doc.close()
        raise RuntimeError(f"Could not open image file: {path}")
    rect = img_doc[0].rect
    page = pdf_doc.new_page(width=rect.width, height=rect.height)
    page.insert_image(rect, stream=raw)
    pdf_bytes = pdf_doc.tobytes()
    img_doc.close()
    pdf_doc.close()
    return {"bytes": pdf_bytes, "width": rect.width, "height": rect.height}


def _normalize_polygon(polygon) -> List[tuple]:
    """
    Convert various polygon formats into a list of (x, y) tuples.

    Acceptable inputs:
      - SDK point objects with .x/.y attributes
      - list of dicts {"x":..., "y":...}
      - list/tuple of (x,y) pairs
      - flat list [x1,y1,x2,y2,...]

    Returns empty list on failure or if polygon is falsy.
    """
    if not polygon:
        return []
    try:
        coords = []
        for pt in polygon:
            # pt may be an object with x,y attributes
            if hasattr(pt, "x") and hasattr(pt, "y"):
                coords.append((float(pt.x), float(pt.y)))
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                coords.append((float(pt[0]), float(pt[1])))
        if coords:
            return coords
    except Exception:
        pass
    # fallback: try interpreting as flat list [x1,y1,x2,y2,...]
    try:
        flat = list(polygon)
        if len(flat) % 2 == 0:
            return [(float(flat[i]), float(flat[i + 1])) for i in range(0, len(flat), 2)]
    except Exception:
        pass
    return []

def extract_text_and_polygons(analyze_result) -> List[Dict[str, Any]]:
    """
    Normalize AnalyzeResult-like object to a list of extraction items.

    Each returned item is:
      {"page": int, "type": "line"|"word", "text": str, "polygon": [(x,y), ...]}

    Works with SDK shapes providing `pages` or `read_results` or `documents`.
    """
    out: List[Dict[str, Any]] = []
    pages = getattr(analyze_result, "pages", None)
    if pages is None:
        pages = getattr(analyze_result, "read_results", None) or getattr(analyze_result, "documents", None) or []

    for p_idx, page in enumerate(pages, start=1):
        # lines
        lines = getattr(page, "lines", None) or getattr(page, "lines_", None) or []
        for ln in lines:
            text = getattr(ln, "content", None) or getattr(ln, "text", None) or ""
            polygon = getattr(ln, "polygon", None) or getattr(ln, "bounding_polygon", None)
            if not polygon and getattr(ln, "bounding_regions", None):
                try:
                    br = ln.bounding_regions[0]
                    polygon = getattr(br, "polygon", None) or getattr(br, "bounding_polygon", None)
                except Exception:
                    polygon = None
            coords = _normalize_polygon(polygon)
            out.append({"page": p_idx, "type": "line", "text": text, "polygon": coords})

        # words
        words = getattr(page, "words", None) or getattr(page, "words_", None) or []
        for w in words:
            text = getattr(w, "content", None) or getattr(w, "text", None) or ""
            polygon = getattr(w, "polygon", None) or getattr(w, "bounding_polygon", None)
            if not polygon and getattr(w, "bounding_regions", None):
                try:
                    br = w.bounding_regions[0]
                    polygon = getattr(br, "polygon", None) or getattr(br, "bounding_polygon", None)
                except Exception:
                    polygon = None
            coords = _normalize_polygon(polygon)
            out.append({"page": p_idx, "type": "word", "text": text, "polygon": coords})
    return out


USERS_DB_PATH = Path("users_db.json")

def _hash(pw: str) -> str:
    return hashlib.sha256((pw or "").encode("utf-8")).hexdigest()

def _load_users() -> Dict[str, Dict[str, Any]]:
    if not USERS_DB_PATH.exists():
        return {}
    try:
        return json.loads(USERS_DB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_users(d: Dict[str, Dict[str, Any]]) -> None:
    USERS_DB_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")