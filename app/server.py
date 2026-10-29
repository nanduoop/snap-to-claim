"""Snap-to-Claim web console. Run: uvicorn app.server:app --reload"""

import json
import os
import re
import sys
import threading
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from agent import STATE_DIR, resume_run, run_agent

APP_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(APP_DIR, "static", "index.html")

app = FastAPI(title="Snap-to-Claim")
_runs = {}
_ID = re.compile(r"^[\w-]{1,64}$")
_EXTS = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png", ".webp": ".webp"}


def _check_id(claim_id):
    if not _ID.match(claim_id or ""):
        raise HTTPException(400, "bad claim id")
    return claim_id


def _state_path(claim_id):
    return os.path.join(STATE_DIR, f"{claim_id}.json")


def _claim_dir(claim_id):
    return os.path.join(STATE_DIR, claim_id)


def _read_state(claim_id):
    try:
        with open(_state_path(claim_id)) as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(404, "unknown claim")
    except json.JSONDecodeError:
        raise HTTPException(503, "state is being written, retry")


def _write_state(claim_id, state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_state_path(claim_id), "w") as f:
        json.dump(state, f, indent=1)


def _background(claim_id, fn):
    if _runs.get(claim_id, {}).get("running"):
        raise HTTPException(409, "run already in progress")
    _runs[claim_id] = {"running": True, "error": None}

    def go():
        try:
            fn()
        except Exception as e:
            _runs[claim_id]["error"] = str(e)
        finally:
            _runs[claim_id]["running"] = False

    threading.Thread(target=go, daemon=True).start()


def _save_upload(claim_id, file, n):
    ext = _EXTS.get(os.path.splitext(file.filename or "")[1].lower(), ".jpg")
    path = os.path.join(_claim_dir(claim_id), f"photo_{n}{ext}")
    os.makedirs(_claim_dir(claim_id), exist_ok=True)
    with open(path, "wb") as out:
        out.write(file.file.read())
    return path


@app.get("/")
def index():
    return FileResponse(INDEX)


@app.post("/claims")
def start_claim(file: UploadFile = File(...)):
    claim_id = "c" + uuid.uuid4().hex[:8]
    photo = _save_upload(claim_id, file, 0)
    _background(claim_id, lambda: run_agent(claim_id, photo))
    return {"claim_id": claim_id}


@app.get("/claims/{claim_id}")
def get_claim(claim_id: str):
    _check_id(claim_id)
    state = _read_state(claim_id)
    info = _runs.get(claim_id, {"running": False, "error": None})
    return {"running": info["running"], "error": info["error"], **state}


@app.get("/claims/{claim_id}/photo/{n}")
def get_photo(claim_id: str, n: int):
    photos = _read_state(_check_id(claim_id))["record"]["photos"]
    if n < 0 or n >= len(photos) or not os.path.exists(photos[n]):
        raise HTTPException(404, "no such photo")
    return FileResponse(photos[n])


@app.get("/claims/{claim_id}/crop/{part_id}")
def get_crop(claim_id: str, part_id: str):
    _check_id(claim_id)
    if not _ID.match(part_id or ""):
        raise HTTPException(400, "bad part id")
    path = os.path.join(STATE_DIR, "crops", claim_id, f"{part_id}.jpg")
    if not os.path.exists(path):
        raise HTTPException(404, "no crop yet")
    return FileResponse(path)


@app.get("/claims/{claim_id}/preview")
def get_preview(claim_id: str):
    _check_id(claim_id)
    rec = _read_state(claim_id)["record"]
    for cand in [rec.get("preview"), os.path.join(_claim_dir(claim_id), "repaired.png")]:
        if cand and os.path.exists(cand):
            return FileResponse(cand)
    raise HTTPException(404, "no preview yet")


@app.post("/claims/{claim_id}/photo")
def add_photo(claim_id: str, file: UploadFile = File(...)):
    _check_id(claim_id)
    state = _read_state(claim_id)
    if state["status"] != "needs_input":
        raise HTTPException(400, f"claim is {state['status']}, not needs_input")
    photo = _save_upload(claim_id, file, len(state["record"]["photos"]))
    _background(claim_id, lambda: resume_run(claim_id, new_image_path=photo))
    return {"status": "running", "photo": photo}


@app.post("/claims/{claim_id}/approve")
def approve(claim_id: str):
    _check_id(claim_id)
    state = _read_state(claim_id)
    if state["status"] not in ("awaiting_signoff", "escalated"):
        raise HTTPException(400, f"claim is {state['status']}")
    state["status"] = "approved"
    state["record"]["status"] = "approved"
    _write_state(claim_id, state)
    return {"status": "approved"}


@app.post("/claims/{claim_id}/reject")
def reject(claim_id: str, notes: str = Form(...)):
    _check_id(claim_id)
    state = _read_state(claim_id)
    if state["status"] not in ("awaiting_signoff", "escalated"):
        raise HTTPException(400, f"claim is {state['status']}")
    if not notes.strip():
        raise HTTPException(400, "notes required")
    state["history"].append({"turn": state["turn"], "plan": "Human adjuster review",
                             "act": "adjuster_reject", "observe": {"rejected": True, "notes": notes}})
    state["status"] = "running"
    state["record"]["status"] = "open"
    state["record"]["refusals"] = 0
    _write_state(claim_id, state)
    _background(claim_id, lambda: resume_run(claim_id))
    return {"status": "running"}
