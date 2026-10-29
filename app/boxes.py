def box_pixels(box, img_w, img_h, pad=0.10):
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
