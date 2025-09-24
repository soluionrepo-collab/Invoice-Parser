import base64
from src.adapters.logger import logger
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import  JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from src.utils_helper import _hash, _load_users, _save_users
from src.utils import process_zip_main
from src.models import SignupRequest, LoginRequest


app = FastAPI(title="Invoice Parser")

# CORS middleware (development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/signup")
def signup(payload: SignupRequest):
    try:
        users = _load_users()
        if payload.name in users:
            raise HTTPException(status_code=400, detail="User already exists")

        users[payload.email] = {
            "full_name": payload.name,
            "password": _hash(payload.password),
            "email": payload.email
        }
        _save_users(users)
        return {"message": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/login_user")
def login(payload: LoginRequest):
    try:
        users = _load_users()
        user = users.get(payload.email)

        if user and user["password"] == _hash(payload.password):
            return {"message": True, "User": payload.email}
        else:
            return {"message": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.post("/upload") 
async def upload_endpoint(model: str = Form(None), file: UploadFile = File(...)):  
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    # (Optional) simple filename validation – allow .zip, .pdf, images
    filename = file.filename.lower()
    allowed_exts = (".zip", ".pdf", ".png", ".jpg", ".jpeg")
    if not any(filename.endswith(ext) for ext in allowed_exts):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    try:
        result = await process_zip_main(upload=file, model=model)
        
        # Transform the response to match what frontend expects
        transformed_result = {
            "model": result.get("model", model),
            "files": []  # Transform results to files array
        }
        
        for item in result.get("results", []):
            if "error" in item:
                # Skip files with errors or include them with error info
                continue
                            
            file_info = {
                "name": item.get("file_name", ""),
                "type": "pdf" if item.get("file_name", "").lower().endswith('.pdf') else "image",
                "mapped_data": item.get("mapping", {}).get("mapped", {}) if item.get("mapping") else {},
                "signature": item.get("signature_verification", None),
                "preview": {
                    "pdf_bytes": base64.b64encode(item.get("image_info", {}).get("bytes", b"")).decode("utf-8") 
                     if item.get("image_info") and item.get("image_info").get("bytes") else None,
                    "width": item.get("image_info", {}).get("width", 2000) if item.get("image_info") else 2000,
                    "height": item.get("image_info", {}).get("height", 2000) if item.get("image_info") else 2000
                }
            }
            transformed_result["files"].append(file_info)
        
        return JSONResponse(status_code=200, content=transformed_result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("upload failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}")

if __name__ == "__main__":
    import uvicorn, webbrowser
    url = "http://127.0.0.1:8000/"
    print(f"Starting server at {url} ...")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)