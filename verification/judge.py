import json
import os
import re

from PIL import Image

from boxes import box_pixels
from meta_client import chat

JUDGE_SYSTEM = (
    "You are an independent claim auditor. You see one image and one damage claim. "
    "Answer only whether the image visibly supports the claim."
)


def _parse_json(text):
    t = re.sub(r"^```(json)?", "", text.strip()).strip()
    t = re.sub(r"```$", "", t).strip()
    m = re.search(r"\{.*\}", t, re.S)
    return json.loads(m.group(0) if m else t)


def judge_findings(record, crop_dir=None):
    crop_dir = crop_dir or "/tmp/snap_judge"
    problems = []
    parts = {p["id"]: p for p in record.parts}
    for finding in record.findings:
        part = parts.get(finding["part_id"])
        if part is None:
            problems.append({"code": "ORPHAN_FINDING", "finding_ids": [finding["id"]],
                             "detail": f"finding {finding['id']} cites unknown part {finding['part_id']}"})
            continue
        concept = part["concept"]
        if part.get("position"):
            concept = f"{part['position']} {concept}"
        claim = f"{concept}: {finding['damage']}, {finding['severity']}"
        photo = part.get("photo") or (record.photos[-1] if record.photos else None)
        if part.get("box") is None:
            image_path = photo
        else:
            img = Image.open(photo)
            crop = img.crop(box_pixels(part["box"], img.width, img.height))
            os.makedirs(crop_dir, exist_ok=True)
            image_path = os.path.join(crop_dir, f"{finding['id']}.jpg")
            crop.save(image_path)
        prompt = (f'Does this image support the damage claim "{claim}"? '
                  'Return ONLY JSON: {"supported": true/false, "reason": "one sentence"}.')
        text = getattr(chat(prompt, image_path=image_path, system=JUDGE_SYSTEM), "content", "") or ""
        try:
            j = _parse_json(text)
        except Exception:
            problems.append({"code": "JUDGE_ERROR", "finding_ids": [finding["id"]],
                             "detail": f"finding {finding['id']} could not be judged"})
            continue
        if not j.get("supported"):
            problems.append({"code": "UNSUPPORTED", "finding_ids": [finding["id"]],
                             "detail": f"finding {finding['id']} '{claim}' unsupported by image: {j.get('reason', '')}"})
    return problems
