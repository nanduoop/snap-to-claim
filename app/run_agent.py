import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import run_agent


def _one_line(x, n=500):
    s = x if isinstance(x, str) else json.dumps(x)
    return s.replace("\n", " ")[:n]


def main():
    if len(sys.argv) < 2:
        print("usage: python app/run_agent.py <image_path> [claim_id]")
        sys.exit(1)
    image = sys.argv[1]
    claim_id = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(os.path.basename(image))[0]

    def show(turn, plan, act, observe):
        print(f"--- turn {turn} ---")
        print(f"PLAN: {_one_line(plan) or '(no plan text)'}")
        print(f"ACT: {_one_line(act)}")
        print(f"OBSERVE: {_one_line(observe)}")

    state = run_agent(claim_id, image, on_turn=show)
    print(f"done: status={state['status']} turns={state['turn']} state={state['state_path']}")


if __name__ == "__main__":
    main()
