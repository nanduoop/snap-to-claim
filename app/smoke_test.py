import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from meta_client import chat, edit_image, segment


def main():
    if len(sys.argv) < 2:
        print("usage: python -m app.smoke_test <image_path>")
        sys.exit(1)
    image_path = sys.argv[1]
    for concept in ["car", "hood", "bumper", "headlight", "tire", "windshield", "dent"]:
        boxes, raw = segment(image_path, prompt=concept, return_raw=True)
        print(f"concept={concept} boxes={len(boxes)} raw={raw[:300]!r}")
    msg = chat("Describe the visible damage briefly.", image_path=image_path)
    text = getattr(msg, "content", "") or ""
    print(f"chat: {text[:200]}")
    out = edit_image(image_path, "Repair the damage, show undamaged condition")
    print(f"edited: {out}")


if __name__ == "__main__":
    main()
