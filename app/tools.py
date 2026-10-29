import json
import os
import re

from PIL import Image

from meta_client import chat, edit_image, segment

TOOLS = [
    {"type": "function", "function": {"name": "segment_parts", "description": "Find car parts in the photo.", "parameters": {"type": "object", "properties": {"concepts": {"type": "array", "items": {"type": "string"}}}, "required": ["concepts"]}}},
    {"type": "function", "function": {"name": "inspect_part", "description": "Crop a part and judge damage.", "parameters": {"type": "object", "properties": {"part_id": {"type": "string"}}, "required": ["part_id"]}}},
    {"type": "function", "function": {"name": "estimate_cost", "description": "Price a finding from the price table.", "parameters": {"type": "object", "properties": {"finding_id": {"type": "string"}}, "required": ["finding_id"]}}},
    {"type": "function", "function": {"name": "request_evidence", "description": "Stop and ask the user for another photo.", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
    {"type": "function", "function": {"name": "render_repair_preview", "description": "Render repaired-car preview.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "submit_claim", "description": "Submit the claim for verification.", "parameters": {"type": "object", "properties": {}}}},
]


def _pixels(box, img_w, img_h, pad=0.10):
    x1, y1, x2, y2 = box["x1"], box["y1"], box["x2"], box["y2"]
    w, h = box.get("w") or img_w, box.get("h") or img_h
    if w != img_w:
        x1, x2 = x1 / w * img_w, x2 / w * img_w
    if h != img_h:
        y1, y2 = y1 / h * img_h, y2 / h * img_h
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    pw, ph = (x2 - x1) * pad, (y2 - y1) * pad
    return (max(0, int(x1 - pw)), max(0, int(y1 - ph)), min(img_w, int(x2 + pw)), min(img_h, int(y2 + ph)))


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
    photo = part.get("photo") or (record.photos[-1] if record.photos else None)
    img = Image.open(photo)
    crop = img.crop(_pixels(part["box"], img.width, img.height))
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
    return {"status": "stub", "message": "verification not implemented yet",
            "line_items": record.line_items, "findings": record.findings}


DISPATCH = {
    "segment_parts": segment_parts,
    "inspect_part": inspect_part,
    "estimate_cost": estimate_cost,
    "request_evidence": request_evidence,
    "render_repair_preview": render_repair_preview,
    "submit_claim": submit_claim,
}
