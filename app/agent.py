import json
import os

from claim_record import ClaimRecord
from meta_client import chat
from tools import DISPATCH, TOOLS

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(APP_DIR, "state")
PLAYBOOK_PATH = os.path.join(APP_DIR, "playbook.md")


def _playbook():
    with open(PLAYBOOK_PATH) as f:
        return f.read()


def _summarize(record):
    parts = [{"id": p["id"], "concept": p["concept"], "position": p.get("position")} for p in record.parts]
    return json.dumps({
        "claim_id": record.claim_id,
        "status": record.status,
        "photos": record.photos,
        "survey": record.survey,
        "parts": parts,
        "findings": record.findings,
        "line_items": record.line_items,
        "evidence_request": record.evidence_request,
        "preview": record.preview,
    }, indent=1)


def _history_text(history):
    lines = []
    for t in history:
        obs = json.dumps(t["observe"])[:1500]
        lines.append(f"Turn {t['turn']}\nPLAN: {t['plan']}\nACT: {t['act']}\nOBSERVE: {obs}")
    return "\n".join(lines)


def _save_state(path, claim_id, turn, status, history, record):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"claim_id": claim_id, "turn": turn, "status": status,
                   "history": history, "record": record.to_dict()}, f, indent=1)


def _run_loop(claim_id, record, history, turn, max_turns, on_turn):
    state_path = os.path.join(STATE_DIR, f"{claim_id}.json")
    crop_dir = os.path.join(STATE_DIR, "crops", claim_id)
    claim_dir = os.path.join(STATE_DIR, claim_id)
    os.makedirs(claim_dir, exist_ok=True)
    preview_path = os.path.join(claim_dir, "repaired.png")
    status = "running"
    while turn < max_turns:
        turn += 1
        prompt = (f"Claim record:\n{_summarize(record)}\n\nHistory:\n{_history_text(history) or '(none)'}\n"
                  f"\nTurn {turn}/{max_turns}. Reply with a one-line plan, then call exactly one tool.")
        if turn == max_turns:
            prompt += " FINAL TURN: you must call submit_claim now."
        attempt_note = ""
        for _ in range(3):
            msg = chat(prompt + attempt_note, tools=TOOLS, system=_playbook(), tool_choice="auto")
            if msg.tool_calls:
                break
            attempt_note = "\nOBSERVATION: You must call exactly one tool this turn."
        plan = (msg.content or "").strip()
        calls = list(msg.tool_calls or [])
        if not calls:
            act, observe = "none", {"error": "model called no tool after 2 retries"}
        else:
            multi_note = None
            if len(calls) > 1:
                multi_note = f"{len(calls)} tool calls returned; only the first was run, the rest were ignored."
            call = calls[0]
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except Exception:
                args = {}
            act = f"{name}({json.dumps(args)})"
            if name not in DISPATCH:
                observe = {"error": f"unknown tool '{name}'. Use one of: {sorted(DISPATCH)}"}
            else:
                try:
                    if name == "inspect_part":
                        observe = DISPATCH[name](record, crop_dir=crop_dir, **args)
                    elif name == "render_repair_preview":
                        args.pop("out_path", None)
                        observe = DISPATCH[name](record, out_path=preview_path)
                    else:
                        observe = DISPATCH[name](record, **args)
                except TypeError as e:
                    observe = {"error": f"bad args for {name}: {e}"}
                except Exception as e:
                    observe = {"error": f"{name} failed: {e}"}
            if multi_note and isinstance(observe, dict):
                observe["note"] = multi_note
        history.append({"turn": turn, "plan": plan, "act": act, "observe": observe})
        if on_turn:
            on_turn(turn, plan, act, observe)
        act_name = act.split("(")[0]
        if act_name == "request_evidence" and isinstance(observe, dict) and observe.get("status") == "needs_input":
            status = "needs_input"
            _save_state(state_path, claim_id, turn, status, history, record)
            break
        if act_name == "submit_claim" and isinstance(observe, dict) and observe.get("status") in ("awaiting_signoff", "escalated"):
            status = observe["status"]
            _save_state(state_path, claim_id, turn, status, history, record)
            break
        _save_state(state_path, claim_id, turn, status, history, record)
    else:
        status = "max_turns"
        _save_state(state_path, claim_id, turn, status, history, record)
    return {"claim_id": claim_id, "turn": turn, "status": status, "history": history,
            "record": record.to_dict(), "state_path": state_path}


def run_agent(claim_id, image_path, max_turns=30, on_turn=None):
    record = ClaimRecord(claim_id)
    record.add_photo(image_path)
    return _run_loop(claim_id, record, [], 0, max_turns, on_turn)


def resume_run(claim_id, new_image_path=None, max_turns=30, on_turn=None):
    state_path = os.path.join(STATE_DIR, f"{claim_id}.json")
    with open(state_path) as f:
        d = json.load(f)
    if d.get("status") in ("awaiting_signoff", "escalated"):
        return d
    record = ClaimRecord.from_dict(d["record"])
    if new_image_path:
        record.add_photo(new_image_path)
        record.status = "open"
    return _run_loop(claim_id, record, d.get("history", []), d.get("turn", 0), max_turns, on_turn)
