---
description: Search the team's KAOS memory for lessons, incidents, and skills relevant to the current task. Use when starting work on a bug, incident, or module that the team may have seen before, or when the user asks "have we hit this before?".
---

# Recall from KAOS memory

Run the search and read the results before answering:

```bash
kaos memory search "$ARGUMENTS" --rank weighted -n 5 --record-hits --format inject
```

- `--rank weighted` prefers lessons that were consulted and worked before (neuroplasticity).
- `--record-hits` tells KAOS which memories were actually useful, so ranking keeps learning.
- If nothing comes back, say so plainly — KAOS recall is literal full-text search; try
  two or three alternative phrasings (e.g. "double charge" vs "duplicate processing")
  before concluding the team has no lesson on this.

When the task ends with a lesson worth keeping, save it:

```bash
kaos memory write claude-code "<one-paragraph lesson: symptom, root cause, fix>" -t insight -k <short-key>
```
