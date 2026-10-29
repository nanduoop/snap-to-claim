import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, ROOT)

from claim_record import ClaimRecord
from tools import DISPATCH, TOOLS, record_missing_part, withdraw_finding
from verification.rules import check_rules


def _record():
    r = ClaimRecord("t")
    r.add_photo("test_images/car_11.jpg")
    return r


def main():
    assert len(TOOLS) == len(DISPATCH) == 10
    assert "withdraw_finding" in DISPATCH

    # same instance, two damages -> CONFLICT naming both findings
    r = _record()
    p1 = r.add_part("bumper", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    f1 = r.add_finding(p1, "scratch", "minor", "a")
    f2 = r.add_finding(p1, "missing", "severe", "b")
    r.add_line_item(f1)
    r.add_line_item(f2)
    probs = check_rules(r)
    assert len(probs) == 1 and probs[0]["code"] == "CONFLICT", probs
    assert probs[0]["finding_ids"] == ["f1", "f2"], probs
    print("same-instance conflict OK")

    # two instances of one concept -> no conflict
    r = _record()
    out_f = record_missing_part(r, "bumper", "front torn off", "severe", position="front")
    p2 = r.add_part("bumper", {"x1": 0, "y1": 0, "x2": 10, "y2": 10}, position="rear")
    f2b = r.add_finding(p2, "scratch", "minor", "scuff")
    r.add_line_item(out_f["finding_id"])
    r.add_line_item(f2b)
    assert out_f["position"] == "front" and r.parts[1]["position"] == "rear"
    assert check_rules(r) == [], check_rules(r)
    print("cross-instance no-conflict + position OK")

    bad = record_missing_part(r, "bumper", "x", position="top")
    assert "error" in bad, bad
    print("bad position rejected OK")

    # withdraw removes finding + items and logs the audit entry
    w = withdraw_finding(r, f2b, "scratch was a reflection")
    assert w["withdrawn"] == f2b and w["removed_line_items"] == ["l2"], w
    assert all(f["id"] != f2b for f in r.findings)
    assert all(i["finding_id"] != f2b for i in r.line_items)
    assert r.withdrawals[0]["reason"] == "scratch was a reflection"
    assert r.withdrawals[0]["finding"]["id"] == f2b
    d = ClaimRecord.from_dict(r.to_dict())
    assert d.withdrawals == r.withdrawals
    assert "error" in withdraw_finding(r, "f99", "x")
    print("withdraw + audit trail OK")

    # every rule problem carries finding_ids
    r = _record()
    r.survey = {"damaged": ["door"], "missing": [], "notes": "x"}
    r.line_items.append({"id": "lx", "finding_id": "f99", "part": "x",
                         "damage": "x", "severity": "x", "low": 0, "high": 0})
    probs = check_rules(r)
    assert {p["code"] for p in probs} == {"ORPHAN_ITEM", "COVERAGE_GAP"}, probs
    for p in probs:
        assert isinstance(p["finding_ids"], list), p
    print("finding_ids on all problems OK")


if __name__ == "__main__":
    main()
