import json
import os
import re

from PIL import Image

from boxes import box_pixels
from claim_record import load_prices
from meta_client import chat, edit_image, segment

TOOLS = [
    {"type": "function", "function": {"name": "segment_parts", "description": "Find car parts in the photo.", "parameters": {"type": "object", "properties": {"concepts": {"type": "array", "items": {"type": "string"}}}, "required": ["concepts"]}}},
    {"type": "function", "function": {"name": "inspect_part", "description": "Crop a part and judge damage.", "parameters": {"type": "object", "properties": {"part_id": {"type": "string"}}, "required": ["part_id"]}}},
    {"type": "function", "function": {"name": "estimate_cost", "description": "Price a finding from the price table.", "parameters": {"type": "object", "properties": {"finding_id": {"type": "string"}}, "required": ["finding_id"]}}},
    {"type": "function", "function": {"name": "request_evidence", "description": "Stop and ask the user for another photo.", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
    {"type": "function", "function": {"name": "render_repair_preview", "description": "Render repaired-car preview.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "submit_claim", "description": "Submit the claim for verification.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "survey_photo", "description": "Survey the full photo for damaged and missing parts.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "record_missing_part", "description": "Record a part that is missing entirely (no box).", "parameters": {"type": "object", "properties": {"part": {"type": "string"}, "rationale": {"type": "string"}, "severity": {"type": "string"}}, "required": ["part", "rationale"]}}},
    {"type": "function", "function": {"name": "dismiss_part", "description": "Explicitly decline to claim a surveyed part, with reason.", "parameters": {"type": "object", "properties": {"part": {"type": "string"}, "reason": {"type": "string"}}, "required": ["part", "reason"]}}},
]


def segment_parts(record, concepts, photo_path=None):
    photo = photo_path or (record.photos[-1] if record.photos else None)
    if not photo:
        return {"error": "no photo"}
    added = []
    for concept in concepts:
        for box in segment(photo, prompt=concept):
            pid = record.add_part(concept, box, photo=photo)
            added.append({"id": pid, "concept": concept, "box": box})
    return {"parts_added": len(added), "parts": added}


def _parse_json(text):
    t = re.sub(r"^```(json)?", "", text.strip()).strip()
    t = re.sub(r"```$", "", t).strip()
    m = re.search(r"\{.*\}", t, re.S)
    return json.loads(m.group(0) if m else t)


def inspect_part(record, part_id, crop_dir=None):
    part = next((p for p in record.parts if p["id"] == part_id), None)
    if not part:
        return {"error": f"unknown part_id {part_id}"}
    if part.get("box") is None:
        return {"error": f"part {part_id} is missing, no box to inspect"}
    photo = part.get("photo") or (record.photos[-1] if record.photos else None)
    img = Image.open(photo)
    crop = img.crop(box_pixels(part["box"], img.width, img.height))
    crop_dir = crop_dir or "/tmp/snap_claim"
    os.makedirs(crop_dir, exist_ok=True)
    crop_path = os.path.join(crop_dir, f"{part_id}.jpg")
    crop.save(crop_path)
    prompt = (
        f"You are a vehicle damage inspector. This is a crop of the car's {part['concept']}. "
        'Return ONLY JSON: {"damaged": true/false, "damage": "scratch|dent|crack|crushed|missing|none", '
        '"severity": "minor|moderate|severe|none", "rationale": "one sentence"}.'
    )
    text = getattr(chat(prompt, image_path=crop_path), "content", "") or ""
    try:
        j = _parse_json(text)
    except Exception as e:
        return {"part_id": part_id, "crop": crop_path, "error": f"bad JSON: {e}", "raw": text[:300]}
    if not j.get("damaged") or j.get("damage") in (None, "none"):
        return {"part_id": part_id, "crop": crop_path, "damaged": False, "rationale": j.get("rationale", "")}
    try:
        fid = record.add_finding(part_id, j["damage"], j["severity"], j.get("rationale", ""))
    except ValueError as e:
        return {"part_id": part_id, "crop": crop_path, "error": str(e), "parsed": j}
    return {"part_id": part_id, "crop": crop_path, "finding_id": fid, **j}


def estimate_cost(record, finding_id):
    try:
        lid = record.add_line_item(finding_id)
    except ValueError as e:
        return {"error": str(e)}
    return {"line_item": next(i for i in record.line_items if i["id"] == lid)}


def request_evidence(record, reason):
    record.status = "needs_input"
    record.evidence_request = reason
    return {"status": "needs_input", "reason": reason}


def render_repair_preview(record, out_path="repaired.png"):
    if not record.photos:
        return {"error": "no photo"}
    out = edit_image(record.photos[-1], "Repair all visible damage, show undamaged condition", out_path=out_path)
    record.preview = out
    return {"preview": out}


def submit_claim(record):
    from verification.gate import run_gate
    status, payload = run_gate(record)
    return {"status": status, **payload}


def survey_photo(record):
    if not record.photos:
        return {"error": "no photo"}
    prompt = (
        "You are a vehicle damage inspector. Look at this full photo of a car. "
        "List which parts look DAMAGED and which parts appear MISSING entirely (e.g. torn-off bumper). "
        "Part names must be from: hood, bumper, fender, door, windshield, headlight, tire, mirror. "
        'Return ONLY JSON: {"damaged": ["part", ...], "missing": ["part", ...], "notes": "one sentence"}.'
    )
    text = getattr(chat(prompt, image_path=record.photos[-1]), "content", "") or ""
    try:
        j = _parse_json(text)
    except Exception as e:
        return {"error": f"bad JSON: {e}", "raw": text[:300]}
    record.survey = j
    return j


def record_missing_part(record, part, rationale, severity="moderate"):
    prices = load_prices()
    if part not in prices:
        return {"error": f"unknown part '{part}'. Use one of: {sorted(prices)}"}
    if severity not in ("minor", "moderate", "severe"):
        return {"error": f"bad severity '{severity}'"}
    pid = record.add_part(part, None)
    fid = record.add_finding(pid, "missing", severity, rationale)
    return {"part_id": pid, "finding_id": fid, "part": part, "damage": "missing", "severity": severity}


def dismiss_part(record, part, reason):
    if part not in load_prices():
        return {"error": f"unknown part '{part}'"}
    return {"dismissed": record.add_dismissal(part, reason)}


DISPATCH = {
    "segment_parts": segment_parts,
    "inspect_part": inspect_part,
    "estimate_cost": estimate_cost,
    "request_evidence": request_evidence,
    "render_repair_preview": render_repair_preview,
    "submit_claim": submit_claim,
    "survey_photo": survey_photo,
    "record_missing_part": record_missing_part,
    "dismiss_part": dismiss_part,
}
