from claim_record import load_prices


def check_rules(record):
    problems = []
    findings = {f["id"]: f for f in record.findings}
    parts = {p["id"]: p for p in record.parts}
    try:
        prices = load_prices()
    except Exception:
        return [{"code": "PRICE_TABLE_UNREADABLE", "detail": "price table could not be loaded"}]

    for item in record.line_items:
        f = findings.get(item.get("finding_id"))
        if f is None:
            problems.append({"code": "ORPHAN_ITEM",
                             "detail": f"line item {item.get('id')} cites unknown finding {item.get('finding_id')}"})
            continue
        part = parts.get(f["part_id"])
        concept = part["concept"] if part else None
        table = prices.get(concept, {}).get(f["damage"], {}).get(f["severity"])
        if table is None or [item.get("low"), item.get("high")] != list(table):
            problems.append({"code": "PRICE_MISMATCH",
                             "detail": f"line item {item.get('id')} price is not from the price table"})

    claimed = {}
    for item in record.line_items:
        f = findings.get(item.get("finding_id"))
        if f is None:
            continue
        part = parts.get(f["part_id"])
        if part is None:
            continue
        claimed.setdefault(part["concept"], set()).add(f["damage"])
    for concept, damages in sorted(claimed.items()):
        if len(damages) > 1:
            problems.append({"code": "CONFLICT",
                             "detail": f"part '{concept}' claimed with conflicting damages: {sorted(damages)}"})

    survey = record.survey or {}
    surveyed = {str(s).strip().lower() for s in (survey.get("damaged") or []) + (survey.get("missing") or [])}
    found = set()
    for f in record.findings:
        part = parts.get(f["part_id"])
        if part:
            found.add(str(part["concept"]).strip().lower())
    dismissed = {str(d.get("part")).strip().lower() for d in record.dismissals}
    for s in sorted(surveyed):
        if s not in found and s not in dismissed:
            problems.append({"code": "COVERAGE_GAP",
                             "detail": f"surveyed part '{s}' has no finding or dismissal"})

    return problems
