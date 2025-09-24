
import json
import ast
import time
from typing import List, Dict, Any
import asyncio
from src.adapters.azure_document_intelligence import async_document_intelligence_client as di
from src.adapters.azure_openai import async_openai_client
from src.adapters.logger import logger
from src.utils_helper import (
    file_to_pdf_bytes,
    extract_text_and_polygons,
    prepare_compact_for_gpt,
    _normalize_polygon,
    ALLOWED_EXT,
    decode_json,
    extract_image_content,
    pdf_to_image_first_page_fitz
)

import os
import zipfile
import shutil
import tempfile
import base64
from fastapi import UploadFile, HTTPException
from src.prompts.system import get_prompt_template
from PIL import Image
import io

TRUNCATE_CHARS = 60
COMPACT_MAX_ITEMS = 60

def _map_by_id_and_polygons(gpt_json: Dict[str, Any], extracted_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Map GPT JSON output to extracted items with polygon coordinates.

    The GPT output can be structured in several ways:
      - values containing "id" or "ids" (preferred)
      - strings that are Python dict-like (e.g., "{'text': '...', 'polygon': 6}")
      - dicts containing "polygon" (either index or coordinates)
      - plain strings that match extracted text

    This function attempts to handle those cases robustly and returns a dict:
      { key: {"text": ..., "polygon": ...}, ... }

    Parameters
    ----------
    gpt_json : Dict[str, Any]
        Parsed JSON object returned by the GPT adapter.
    extracted_items : List[Dict[str, Any]]
        List of DI-extracted items where each item has keys
        like {"page", "type", "text", "polygon"}.

    Returns
    -------
    Dict[str, Any]
        Mapping of GPT keys to text+polygon objects.
    """
    mapped: Dict[str, Any] = {}
    for k, v in gpt_json.items():
        try:
            # structured with id/ids
            if isinstance(v, dict) and ("id" in v or "ids" in v):
                ids = v.get("ids") or ([v.get("id")] if v.get("id") is not None else [])
                texts, polygons = [], []
                for idx in ids:
                    try:
                        src = extracted_items[int(idx)]
                        texts.append(src.get("text"))
                        polygons.append(src.get("polygon"))
                    except Exception:
                        continue
                mapped[k] = {
                    "text": v.get("text") if isinstance(v.get("text"), str) else (texts[0] if texts else ""),
                    "polygon": polygons[0] if len(polygons) == 1 else polygons,
                }
                continue

            # string that looks like Python dict (e.g. "{'text': '...', 'polygon': 6}")
            if isinstance(v, str):
                s = v.strip()
                if s.startswith("{") and ("'text'" in s or '"text"' in s):
                    try:
                        parsed = ast.literal_eval(s)
                        txt = parsed.get("text") if isinstance(parsed, dict) else None
                        poly_idx = parsed.get("polygon") if isinstance(parsed, dict) else None
                        if isinstance(poly_idx, int):
                            try:
                                src = extracted_items[int(poly_idx)]
                                mapped[k] = {"text": txt or src.get("text"), "polygon": src.get("polygon")}
                            except Exception:
                                mapped[k] = {"text": txt or "", "polygon": None}
                        else:
                            if isinstance(poly_idx, (list, tuple)):
                                mapped[k] = {"text": txt or "", "polygon": _normalize_polygon(poly_idx)}
                            else:
                                mapped[k] = {"text": txt or str(parsed)}
                        continue
                    except Exception:
                        pass

            # dict with polygon index or coords
            if isinstance(v, dict) and isinstance(v.get("polygon", None), (int, list, tuple)):
                poly = v.get("polygon")
                if isinstance(poly, int):
                    try:
                        src = extracted_items[int(poly)]
                        mapped[k] = {"text": v.get("text") or src.get("text"), "polygon": src.get("polygon")}
                    except Exception:
                        mapped[k] = {"text": v.get("text") or "", "polygon": None}
                else:
                    mapped[k] = {"text": v.get("text") or "", "polygon": _normalize_polygon(poly)}
                continue

            # plain string fallback -> find exact match
            if isinstance(v, str):
                found = None
                for it in extracted_items:
                    if (it.get("text") or "").strip() == v.strip():
                        found = it
                        break
                if found:
                    mapped[k] = {"text": v, "polygon": found.get("polygon")}
                else:
                    mapped[k] = {"text": v}
                continue

            mapped[k] = {"text": str(v)}
        except Exception as e:
            logger.exception("Mapping error for key=%s: %s", k, e)
            mapped[k] = {"text": str(v)}
    return mapped

async def pipeline_mapping(path: str, model: str) -> Dict[str, Any]:
    
    basename = path.split("/")[-1]
    system_prompt_mapping = get_prompt_template("data_extraction.jinja2").render()
    out: Dict[str, Any] = {"file": path, "mapping": None, "image_info": None}

    try:
        pdf_bytes = await file_to_pdf_bytes(path)
        out["image_info"] = pdf_bytes
    except Exception as e:
        out["mapping"] = {"error": f"read/convert failed: {e}"}
        logger.error("[%s] pipeline_mapping read failed: %s", basename, e, exc_info=True)
        return out

    try:
        logger.info("[%s] pipeline_mapping begin analyze", basename)
        poller = await di.begin_analyze_async(pdf_bytes=pdf_bytes["bytes"], model_id="prebuilt-layout")
    except Exception as e:
        out["mapping"] = {"error": f"begin_analyze_async failed: {e}"}
        logger.error("[%s] begin_analyze_async failed: %s", basename, e, exc_info=True)
        return out

    try:
        result = await poller.result()
    except Exception as e:
        out["mapping"] = {"error": f"analyze failed: {e}"}
        logger.error("[%s] poller result failed: %s", basename, e, exc_info=True)
        return out

    try:
        extracted_items = extract_text_and_polygons(result)
        compact = prepare_compact_for_gpt(extracted_items, TRUNCATE_CHARS, COMPACT_MAX_ITEMS)
        user_payload = {"items": compact, "instruction": "Return JSON ONLY. Map standardized keys to objects containing the original 'id'."}
        user_prompt_str = json.dumps(user_payload, ensure_ascii=False)

        resp = await async_openai_client.get_response(
            system_prompt=system_prompt_mapping,
            user_prompt=user_prompt_str,
            model=model,
            json_mode=True,
        )

        gpt_json=decode_json(resp.content)

        mapped = _map_by_id_and_polygons(gpt_json, extracted_items)
        out["mapping"] = {"mapped": mapped, "gpt_time": resp.latency_seconds}
        return out
    except Exception as e:
        out["mapping"] = {"error": f"mapping failed: {e}"}
        logger.exception("[%s] mapping failed: %s", basename, e)
        return out

async def pipeline_signature(path: str, model: str ) -> Dict[str, Any]:
    basename = path.split("/")[-1]
    system_prompt_signature = get_prompt_template("signature_validation.jinja2").render()
    try:
        user_prompt = await asyncio.to_thread(extract_image_content, path)
        print(model)
        resp = await async_openai_client.get_response(
            system_prompt=system_prompt_signature,
            user_prompt=[user_prompt],
            model=model,
            json_mode=False,
        )
        response = decode_json(resp.content)

        if str(response.get('signature', "false")).lower() == "true":
            return True
        else:
            return False
    except Exception as e:
        logger.exception("[%s] pipeline_signature failed: %s", basename, e)
        raise

async def process_both_for_file(path: str, model: str) -> Dict[str, Any]:
    file_name = os.path.basename(path)
    
    mapping_task = asyncio.create_task(pipeline_mapping(path, model=model))
    sig_task = asyncio.create_task(pipeline_signature(path, model=model))

    mapping_res, sig_res = await asyncio.gather(mapping_task, sig_task)
    combined: Dict[str, Any] = {
        "file_name": file_name,
        "mapping": mapping_res.get("mapping"),
        "signature_verification": sig_res,
        "image_info": mapping_res.get("image_info")
    }
    return combined

async def _save_upload_to_dir(upload: UploadFile, target_dir: str) -> str:
    """Save FastAPI UploadFile to disk and return the path."""
    dest_path = os.path.join(target_dir, os.path.basename(upload.filename))
    content = await upload.read()
    with open(dest_path, "wb") as out_f:
        out_f.write(content)
    return dest_path

def _extract_zip_to_dir(zip_path: str, target_dir: str) -> List[str]:
    """Extract all files from zip_path into target_dir and return allowed file paths."""
    extracted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            name = os.path.basename(member.filename)
            if not name:
                continue
            target_path = os.path.join(target_dir, name)
            with zf.open(member) as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            # only keep files with allowed extensions
            _, ext = os.path.splitext(target_path)
            if ext.lower() in ALLOWED_EXT:
                extracted.append(target_path)
            else:
                # Optionally remove unsupported files
                try:
                    os.remove(target_path)
                except Exception:
                    pass
    return extracted

async def process_zip_main(upload: UploadFile, model: str) -> dict:
    workspace = tempfile.mkdtemp(prefix="di_api_")
    try:
        # save uploaded zip to workspace
        zip_path = await _save_upload_to_dir(upload, workspace)

        _, ext = os.path.splitext(zip_path)
        ext = ext.lower()

        # extract allowed files
        if ext == ".zip":
            saved_files = _extract_zip_to_dir(zip_path, workspace)
        else:
            saved_files = [zip_path]

        if not saved_files:
            raise HTTPException(
                status_code=400,
                detail=f"No supported files found in uploaded zip (allowed extensions: {', '.join(sorted(ALLOWED_EXT))})"
            )
        
         # Create a flat list of all tasks
        tasks = []
        for path in saved_files:
            tasks.append(pipeline_mapping(path, model))
            tasks.append(pipeline_signature(path, model))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Reassemble results safely
        combined_results = []
        for i, path in enumerate(saved_files):
            file_name = os.path.basename(path)
            
            # Get results for the current file
            mapping_res = results[2 * i]
            sig_res = results[2 * i + 1]

            if isinstance(mapping_res, Exception):
                logger.error("Mapping failed for %s: %s", file_name, mapping_res)
                combined_results.append({"file_name": file_name, "error": f"Mapping process failed: {mapping_res}"})
                continue # Skip to the next file
            
            if isinstance(sig_res, Exception):
                logger.error("Signature check failed for %s: %s", file_name, sig_res)
                combined_results.append({"file_name": file_name, "error": f"Signature process failed: {sig_res}"})
                continue # Skip to the next file

            # If both succeeded, append the combined result
            combined_results.append({
                "file_name": file_name,
                "mapping": mapping_res.get("mapping"),
                "signature_verification": sig_res,
                "image_info": mapping_res.get("image_info")
            })

        return {
            "model": model,
            "results": combined_results,
        }

    finally:
        try:
            shutil.rmtree(workspace)
        except Exception as cleanup_exc:
            logger.warning("Failed to remove workspace %s: %s", workspace, cleanup_exc)