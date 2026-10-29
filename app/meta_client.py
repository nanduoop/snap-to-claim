import base64
import os
import re

import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url="https://api.meta.ai/v1",
    api_key=os.getenv("MODEL_API_KEY"),
)

CHAT_MODEL = "muse-spark-1.3"
SEGMENT_MODEL = "sam-3.1"
EDIT_MODEL = "muse-image-1.0"


def _data_url(image_path):
    ext = os.path.splitext(image_path)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


def chat(prompt, image_path=None, tools=None, model=CHAT_MODEL, system=None, tool_choice=None):
    content = [{"type": "text", "text": prompt}]
    if image_path:
        content.append({"type": "image_url", "image_url": {"url": _data_url(image_path)}})
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})
    kwargs = {"tool_choice": tool_choice} if tool_choice is not None else {}
    resp = client.chat.completions.create(model=model, messages=messages, tools=tools, **kwargs)
    return resp.choices[0].message


def segment(image_path, prompt="segment damage", model=SEGMENT_MODEL, return_raw=False):
    resp = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": _data_url(image_path)},
                ],
            }
        ],
    )
    text = getattr(resp, "output_text", "") or str(resp)
    boxes = []
    for m in re.finditer(r"<\|box;(.*?)\|>", text):
        box = {}
        for part in m.group(1).split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                try:
                    box[k] = int(v)
                except ValueError:
                    try:
                        box[k] = float(v)
                    except ValueError:
                        box[k] = v
        boxes.append(box)
    if return_raw:
        return boxes, text
    return boxes


def edit_image(image_path, prompt, model=EDIT_MODEL, out_path="repaired.png"):
    with open(image_path, "rb") as f:
        resp = client.images.edit(model=model, image=f, prompt=prompt)
    item = resp.data[0]
    if getattr(item, "b64_json", None):
        with open(out_path, "wb") as out:
            out.write(base64.b64decode(item.b64_json))
    else:
        r = requests.get(item.url, timeout=60)
        r.raise_for_status()
        with open(out_path, "wb") as out:
            out.write(r.content)
    return out_path
