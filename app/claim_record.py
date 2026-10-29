import json
import os

PRICES_PATH = os.path.join(os.path.dirname(__file__), "data", "prices.json")


def load_prices():
    with open(PRICES_PATH) as f:
        return json.load(f)


class ClaimRecord:
    def __init__(self, claim_id="claim1"):
        self.claim_id = claim_id
        self.photos = []
        self.parts = []
        self.findings = []
        self.line_items = []
        self.status = "open"
        self.evidence_request = None
        self.preview = None
        self.survey = None
        self.dismissals = []
        self.withdrawals = []
        self.refusals = 0
        self._n_part = 0
        self._n_finding = 0
        self._n_item = 0

    def add_photo(self, path):
        self.photos.append(path)
        return path

    def add_part(self, concept, box, photo=None, position=None):
        self._n_part += 1
        part = {
            "id": f"p{self._n_part}",
            "concept": concept,
            "box": box,
            "photo": photo or (self.photos[-1] if self.photos else None),
            "position": position,
        }
        self.parts.append(part)
        return part["id"]

    def add_finding(self, part_id, damage, severity, rationale):
        if not any(p["id"] == part_id for p in self.parts):
            raise ValueError(f"unknown part_id: {part_id}")
        self._n_finding += 1
        finding = {
            "id": f"f{self._n_finding}",
            "part_id": part_id,
            "damage": damage,
            "severity": severity,
            "rationale": rationale,
        }
        self.findings.append(finding)
        return finding["id"]

    def add_dismissal(self, part, reason):
        entry = {"part": part, "reason": reason}
        self.dismissals.append(entry)
        return entry

    def withdraw_finding(self, finding_id, reason):
        finding = next((x for x in self.findings if x["id"] == finding_id), None)
        if finding is None:
            raise ValueError(f"unknown finding_id: {finding_id}")
        removed = [i for i in self.line_items if i["finding_id"] == finding_id]
        self.findings = [x for x in self.findings if x["id"] != finding_id]
        self.line_items = [i for i in self.line_items if i["finding_id"] != finding_id]
        entry = {"finding": finding, "line_items": removed, "reason": reason}
        self.withdrawals.append(entry)
        return entry

    def add_line_item(self, finding_id, low=None, high=None):
        finding = next((x for x in self.findings if x["id"] == finding_id), None)
        if finding is None:
            raise ValueError(f"unknown finding_id: {finding_id}")
        part = next((p for p in self.parts if p["id"] == finding["part_id"]), None)
        concept = part["concept"] if part else None
        try:
            table_low, table_high = load_prices()[concept][finding["damage"]][finding["severity"]]
        except KeyError:
            raise ValueError(f"no price for {concept} x {finding['damage']} x {finding['severity']}")
        if low is None:
            low = table_low
        if high is None:
            high = table_high
        if low != table_low or high != table_high:
            raise ValueError(f"price [{low},{high}] not from table [{table_low},{table_high}]")
        self._n_item += 1
        item = {
            "id": f"l{self._n_item}",
            "finding_id": finding_id,
            "part": concept,
            "damage": finding["damage"],
            "severity": finding["severity"],
            "low": low,
            "high": high,
        }
        self.line_items.append(item)
        return item["id"]

    def to_dict(self):
        return {
            "claim_id": self.claim_id,
            "photos": self.photos,
            "parts": self.parts,
            "findings": self.findings,
            "line_items": self.line_items,
            "status": self.status,
            "evidence_request": self.evidence_request,
            "preview": self.preview,
            "survey": self.survey,
            "dismissals": self.dismissals,
            "withdrawals": self.withdrawals,
            "refusals": self.refusals,
        }

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def from_dict(cls, d):
        r = cls(d.get("claim_id", "claim1"))
        r.photos = d.get("photos", [])
        r.parts = d.get("parts", [])
        r.findings = d.get("findings", [])
        r.line_items = d.get("line_items", [])
        r.status = d.get("status", "open")
        r.evidence_request = d.get("evidence_request")
        r.preview = d.get("preview")
        r.survey = d.get("survey")
        r.dismissals = d.get("dismissals", [])
        r.withdrawals = d.get("withdrawals", [])
        r.refusals = d.get("refusals", 0)
        r._n_part = len(r.parts)
        r._n_finding = len(r.findings)
        r._n_item = len(r.line_items)
        return r
