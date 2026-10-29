"""Extract evenly spaced frames from a walkaround video."""

import os


def extract_frames(video_path, out_dir, n=12):
    import cv2

    os.makedirs(out_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        raise ValueError(f"cannot read video: {video_path}")
    idxs = sorted({round(i * (total - 1) / (n - 1)) for i in range(n)}) if n > 1 else [0]
    paths = []
    for j, idx in enumerate(idxs):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        p = os.path.join(out_dir, f"frame_{j:02d}.jpg")
        cv2.imwrite(p, frame)
        paths.append(p)
    cap.release()
    if not paths:
        raise ValueError(f"no frames extracted: {video_path}")
    return paths
