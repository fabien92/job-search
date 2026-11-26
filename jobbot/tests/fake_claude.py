#!/usr/bin/env python3
"""Stands in for `claude -p` in tests: scores every job in the batch and prints a result JSON.

Behaviour from $FAKE_CLAUDE_MODE: ok (default) | auth (login failure) | noscores (forgets the file).
Writes the argv to $JOBBOT_STATE_DIR/runs/fake-claude-argv.json for assertions.
"""
import json
import os
import sys
from pathlib import Path

argv = sys.argv[1:]
state = Path(os.environ["JOBBOT_STATE_DIR"])
(state / "runs" / "fake-claude-argv.json").write_text(json.dumps(argv))
prompt = argv[argv.index("-p") + 1]
run_id = prompt.split()[1]
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if prompt.startswith("/jobbot-go "):
    # /jobbot-go: write cv_overrides.tex. FAKE_GO_MODE: ok | evil (forbidden TeX) | none (writes nothing)
    request = json.loads((state / "runs" / f"go-{run_id}-request.json").read_text())
    Path(request["posting_path"]).read_text()  # the archived posting must exist
    go_mode = os.environ.get("FAKE_GO_MODE", "ok")
    body = {"ok": "% adapted for the posting\n\\renewcommand{\\cvHeadline}{IT Delivery Manager \\textbullet\\ Release \\& ITIL}\n"
                  "\\renewcommand{\\expCurrentBlocks}{\\expProj\\expMgmt\\expTech}\n",
            "evil": "\\renewcommand{\\cvHeadline}{x\\directlua{os.execute('touch /tmp/pwned')}}\n"}.get(go_mode)
    if body:
        Path(request["output_path"]).write_text(body, encoding="utf-8")
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "cvHeadline",
                      "total_cost_usd": 0.07, "permission_denials": []}))
    sys.exit(0)
if prompt.startswith(("/jobbot-discover ", "/jobbot-spontaneous ")):
    # V3: copy $FAKE_V3_OUTPUT (JSON text) to the request's output_path; empty = writes nothing.
    kind = "discover" if prompt.startswith("/jobbot-discover ") else "spont"
    request = json.loads((state / "runs" / f"{kind}-{run_id}-request.json").read_text())
    if os.environ.get("FAKE_V3_OUTPUT"):
        Path(request["output_path"]).write_text(os.environ["FAKE_V3_OUTPUT"], encoding="utf-8")
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": kind,
                      "total_cost_usd": 0.2, "permission_denials": []}))
    sys.exit(0)
if mode == "auth":
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                      "errors": ["OAuth token has expired. Please run /login"], "total_cost_usd": 0}))
    sys.exit(1)
batch = json.loads((state / "runs" / f"{run_id}-batch.json").read_text())
scores = []
for i, job in enumerate(batch["jobs"]):
    Path(job["text_path"]).read_text()  # the cleaned posting must exist
    scores.append({"ref": job["ref"], "score": 90 - 30 * i, "reject_reason": None, "flags": [], "contract": "permanent",
                   "remote": "hybrid", "salary": job.get("salary"), "justification": f"fake score {i}",
                   "variant": "techlead" if i == 0 else "nonexistent", "adapt": i == 0, "adapt_reason": "fake"})
if mode != "noscores":
    (state / "runs" / f"{run_id}-scores.json").write_text(json.dumps({"run_id": run_id, "scores": scores}))
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": f"{len(scores)} scored",
                  "total_cost_usd": 0.12, "permission_denials": []}))
