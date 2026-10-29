import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claim_record import ClaimRecord
from tools import inspect_part, segment_parts


def main():
    photo = sys.argv[1] if len(sys.argv) > 1 else "test_images/car_11.jpg"
    record = ClaimRecord()
    record.add_photo(photo)
    concepts = ["hood", "bumper", "fender", "door", "windshield", "headlight", "tire", "mirror"]
    crop_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "crops")
    r = segment_parts(record, concepts)
    print(f"parts_added: {r.get('parts_added')}")
    for p in list(record.parts):
        print(f"part {p['id']} {p['concept']} {p['box']}")
        print(inspect_part(record, p["id"], crop_dir=crop_dir))
    print("findings:")
    for f in record.findings:
        print(f)


if __name__ == "__main__":
    main()
