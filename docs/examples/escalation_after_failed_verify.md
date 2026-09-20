# Example trace: escalation_after_failed_verify

Clip `r_red_to_white.mp4`, policy `fixed`, status **passed**, 5 iterations. Fixed policy on a full-frame red<->white strobe: S1, S2 and S4 each come back from the analyzer as 'still failing' and the policy escalates until S5 passes; the red segment is fixed by S3 in one step. Every escalation is caused by a verify result. Full JSONL next to this file.

| seq | kind | what happened | role in the loop |
|---|---|---|---|
| 2 | tool_result | verdict fail, 2 segment(s): g000 general 4.0Hz dL=0.7697 area=1.0; r001 red 4.0Hz dL=0.9734 area=1.0 | perception |
| 4 | tool_result | verdict fail, 2 segment(s): g000 general 4.0Hz dL=0.7697 area=1.0; r001 red 4.0Hz dL=0.9734 area=1.0 | perception |
| 6 | tool_result | hints: S1 alpha 0.061, regional=False; attempts so far 0 | perception |
| 7 | tool_call | render S1 {} on g000 | action (fixed policy) |
| 10 | tool_result | analyzer: passes_for_type=False; still failing: general 4.0Hz area 1.0 | perception after action |
| 11 | decision | {"segment_id": "g000", "note": "S1 still fails (still failing: general 4.0Hz area 1.0); escalating"} | fixed_policy |
| 12 | tool_call | render S2 {} on g000 | **follows from the verify result above** (fixed policy escalation) |
| 15 | tool_result | analyzer: passes_for_type=False; still failing: general 4.0Hz area 1.0 | perception after action |
| 16 | decision | {"segment_id": "g000", "note": "S2 still fails (still failing: general 4.0Hz area 1.0); escalating"} | fixed_policy |
| 17 | tool_call | render S4 {"base": "S1"} on g000 | **follows from the verify result above** (fixed policy escalation) |
| 20 | tool_result | analyzer: passes_for_type=False; still failing: general 4.0Hz area 1.0 | perception after action |
| 21 | decision | {"segment_id": "g000", "note": "S4 still fails (still failing: general 4.0Hz area 1.0); escalating"} | fixed_policy |
| 22 | tool_call | render S5 {} on g000 | **follows from the verify result above** (fixed policy escalation) |
| 25 | tool_result | analyzer: passes_for_type=True; no remaining general hazard in the re-analysed segment | perception after action |
| 26 | tool_call | accept_candidate {"candidate_id": "g000-c4"} | **follows from the verify result above** |
| 27 | decision | {"segment_id": "g000", "candidate_id": "g000-c4", "strategy": "S5", "params": {"target_hz": 2.5}} | accept |
| 30 | tool_result | hints: S1 alpha 0.048, regional=False; attempts so far 0 | perception |
| 31 | tool_call | render S3 {} on r001 | action (fixed policy) |
| 34 | tool_result | analyzer: passes_for_type=True; no remaining red hazard in the re-analysed segment | perception after action |
| 35 | tool_call | accept_candidate {"candidate_id": "r001-c1"} | **follows from the verify result above** |
| 36 | decision | {"segment_id": "r001", "candidate_id": "r001-c1", "strategy": "S3", "params": {"strength": 0.6, "ratio_floor": 0.7}} | accept |
| 39 | decision | {"status": "passed", "after_verdict": "pass", "frames_out": 150, "sync_ok": true} | finalize |
