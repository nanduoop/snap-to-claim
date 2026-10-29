"""Download free-licensed damaged-car photos from Wikimedia Commons for testing.

Usage: python3 test_images/fetch_images.py
Saves up to 10 JPEGs into test_images/ plus CREDITS.md with license info.
"""
import json
import pathlib
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).parent
UA = {"User-Agent": "snap-to-claim/0.1 (hackathon test images)"}
QUERIES = ["dented car", "car accident damage", "damaged car bumper", "car crash front damage"]
MAX_IMAGES = 10


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def search(query):
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 15,
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1280,
    }
    data = get_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params))
    return data.get("query", {}).get("pages", {}).values()


def main():
    seen, credits = set(), []
    for q in QUERIES:
        for page in search(q):
            if len(credits) >= MAX_IMAGES:
                break
            title = page["title"]
            info = page["imageinfo"][0]
            url = info.get("thumburl") or info["url"]
            if title in seen or not url.lower().endswith((".jpg", ".jpeg")):
                continue
            seen.add(title)
            meta = info.get("extmetadata", {})
            license_name = meta.get("LicenseShortName", {}).get("value", "unknown")
            name = f"car_{len(credits) + 1:02d}.jpg"
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                (HERE / name).write_bytes(r.read())
            credits.append(f"- {name}: [{title}]({info['descriptionurl']}), {license_name}")
            print("saved", name, "-", title)
    (HERE / "CREDITS.md").write_text("# Test image credits (Wikimedia Commons)\n\n" + "\n".join(credits) + "\n")
    print(f"\nDone: {len(credits)} images. Open test_images/ and keep the ones with clearly visible damage.")


if __name__ == "__main__":
    main()
