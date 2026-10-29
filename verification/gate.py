from verification.judge import judge_findings
from verification.rules import check_rules

MAX_REFUSALS = 3


def run_gate(record):
    problems = check_rules(record)
    if not problems:
        problems = judge_findings(record)
    if problems:
        record.refusals += 1
        if record.refusals >= MAX_REFUSALS:
            record.status = "escalated"
            return ("escalated", {"refusals": record.refusals, "problems": problems,
                                  "message": "escalated to human adjuster after 3 refusals"})
        return ("refused", {"refusals": record.refusals, "problems": problems})
    total_low = sum(i["low"] for i in record.line_items)
    total_high = sum(i["high"] for i in record.line_items)
    record.status = "awaiting_signoff"
    return ("awaiting_signoff", {"total_low": total_low, "total_high": total_high,
                                 "line_items": record.line_items})
