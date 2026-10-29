import json
import os
import re

from PIL import Image

from boxes import box_pixels
from claim_record import load_prices
from meta_client import chat, edit_image, segment

HIDDEN_AREAS = ["engine", "radiator", "suspension", "frame", "airbags", "electrical"]

TOOLS = [
    {"type": "function", "function": {"name": "segment_parts", "description": "Find car parts in the photo.", "parameters": {"type": "object", "properties": {"concepts": {"type": "array", "items": {"type": "string"}}}, "required": ["concepts"]}}},
    {"type": "function", "function": {"name": "inspect_part", "description": "Crop a part and judge damage.", "parameters": {"type": "object", "properties": {"part_id": {"type": "string"}}, "required": ["part_id"]}}},
    {"type": "function", "function": {"name": "estimate_cost", "description": "Price a finding from the price table.", "parameters": {"type": "object", "properties": {"finding_id": {"type": "string"}}, "required": ["finding_id"]}}},
    {"type": "function", "function": {"name": "request_evidence", "description": "Stop and ask the user for another photo.", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
    {"type": "function", "function": {"name": "render_repair_preview", "description": "Render repaired-car preview.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "submit_claim", "description": "Submit the claim for verification.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "survey_photo", "description": "Survey the full photo for damaged and missing parts.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "record_missing_part", "description": "Record a part that is missing entirely (no box).", "parameters": {"type": "object", "properties": {"part": {"type": "string"}, "rationale": {"type": "string"}, "severity": {"type": "string"}, "position": {"type": "string"}}, "required": ["part", "rationale"]}}},
    {"type": "function", "function": {"name": "dismiss_part", "description": "Explicitly decline to claim a surveyed part or hidden-risk area, with reason.", "parameters": {"type": "object", "properties": {"part": {"type": "string"}, "reason": {"type": "string"}}, "required": ["part", "reason"]}}},
    {"type": "function", "function": {"name": "withdraw_finding", "description": "Drop a bad finding and its line items, with reason.", "parameters": {"type": "object", "properties": {"finding_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["finding_id", "reason"]}}},
    {"type": "function", "function": {"name": "flag_hidden_damage", "description": "Flag suspected hidden damage for in-person inspection (no price).", "parameters": {"type": "object", "properties": {"area": {"type": "string"}, "reason": {"type": "string"}}, "required": ["area", "reason"]}}},
    {"type": "function", "function": {"name": "select_frames", "description": "Pick the best video frame per car side and triage each side.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "mark_possible_damage", "description": "Mark a part as possible damage (no price).", "parameters": {"type": "object", "properties": {"part_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["part_id", "reason"]}}},
]


def segment_parts(record, concepts, photo_path=None):
    photo = photo_path or (record.photos[-1] if record.photos else None)
    if not photo:
        return {"error": "no photo"}
    added = []
    side = _side_of(record, photo)
    for concept in concepts:
        for box in segment(photo, prompt=concept):
            pid = record.add_part(concept, box, photo=photo, position=side)
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
    label = part["concept"]
    if part.get("position"):
        label = f"{part['position']} {label}"
    prompt = (
        f"You are a vehicle damage inspector. This is a crop of the car's {label}. "
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
        "Also list hidden_risk areas (engine, radiator, suspension, frame, airbags, electrical) "
        "when you see signs of concealed damage (exposed engine bay, deployed airbags, bent wheel alignment, fluid leaks). "
        'Return ONLY JSON: {"damaged": ["part", ...], "missing": ["part", ...], "hidden_risk": ["area", ...], "notes": "one sentence"}.'
    )
    text = getattr(chat(prompt, image_path=record.photos[-1]), "content", "") or ""
    try:
        j = _parse_json(text)
    except Exception as e:
        return {"error": f"bad JSON: {e}", "raw": text[:300]}
    record.survey = j
    return j


def record_missing_part(record, part, rationale, severity="moderate", position=None):
    prices = load_prices()
    if part not in prices:
        return {"error": f"unknown part '{part}'. Use one of: {sorted(prices)}"}
    if severity not in ("minor", "moderate", "severe"):
        return {"error": f"bad severity '{severity}'"}
    if position is not None and position not in ("front", "rear", "left", "right"):
        return {"error": f"bad position '{position}'"}
    pid = record.add_part(part, None, position=position)
    fid = record.add_finding(pid, "missing", severity, rationale)
    return {"part_id": pid, "finding_id": fid, "part": part, "damage": "missing",
            "severity": severity, "position": position}


def withdraw_finding(record, finding_id, reason):
    try:
        entry = record.withdraw_finding(finding_id, reason)
    except ValueError as e:
        return {"error": str(e)}
    return {"withdrawn": finding_id,
            "removed_line_items": [i["id"] for i in entry["line_items"]]}


def dismiss_part(record, part, reason):
    if part not in load_prices() and part not in HIDDEN_AREAS and part not in ("front", "rear", "left", "right"):
        return {"error": f"unknown part, area, or side '{part}'"}
    return {"dismissed": record.add_dismissal(part, reason)}


def flag_hidden_damage(record, area, reason):
    if area not in HIDDEN_AREAS:
        return {"error": f"unknown area '{area}'. Use one of: {HIDDEN_AREAS}"}
    return {"flagged": record.add_flag(area, reason)}


SIDES = ["front", "rear", "left", "right"]
TRIAGE = ["clear_damage", "possible_minor", "no_damage"]


def _side_of(record, photo):
    for side, info in (record.sides or {}).items():
        if info.get("photo") == photo:
            return side
    return None


def select_frames(record):
    frames = record.frames or []
    if not frames:
        return {"error": "no video frames on this claim"}
    prompt = (
        f"You are a vehicle damage inspector. These {len(frames)} frames come from a walkaround video, "
        f"in order, indexed 0 to {len(frames) - 1}. For each visible car side (front, rear, left, right), "
        "pick the single best frame index and triage it: clear_damage, possible_minor, or no_damage. "
        'Return ONLY JSON: {"sides": {"front": {"frame": 0, "triage": "clear_damage"}, ...}}.'
    )
    text = getattr(chat(prompt, images=frames), "content", "") or ""
    try:
        j = _parse_json(text)
    except Exception as e:
        return {"error": f"bad JSON: {e}", "raw": text[:300]}
    picked = {}
    for side, info in (j.get("sides") or {}).items():
        if side not in SIDES:
            return {"error": f"bad side '{side}'", "raw": text[:300]}
        try:
            idx = int(info.get("frame"))
        except (TypeError, ValueError):
            return {"error": f"bad frame index for '{side}'", "raw": text[:300]}
        if not 0 <= idx < len(frames) or info.get("triage") not in TRIAGE:
            return {"error": f"bad frame/triage for '{side}'", "raw": text[:300]}
        picked[side] = {"frame": idx, "photo": frames[idx], "triage": info["triage"]}
    if not picked:
        return {"error": "no sides selected", "raw": text[:300]}
    record.sides = picked
    for side in SIDES:
        if side in picked:
            record.add_photo(picked[side]["photo"])
    return {"sides": picked}


def mark_possible_damage(record, part_id, reason):
    try:
        entry = record.add_possible(part_id, reason)
    except ValueError as e:
        return {"error": str(e)}
    return {"marked": entry}


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
    "withdraw_finding": withdraw_finding,
    "flag_hidden_damage": flag_hidden_damage,
    "select_frames": select_frames,
    "mark_possible_damage": mark_possible_damage,
}
