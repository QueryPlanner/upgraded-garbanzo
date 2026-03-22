# Agent memory log

Append-only markdown notes the agent records for later recall. Each entry should be
dated and scannable (short title + bullets).

## How to use (agent)

- **Write:** In Docker, append new facts with `docker_bash_execute` and shell
  redirection, e.g. `printf '\\n## 2026-03-22 — Topic\\n- fact\\n' >> /app/memory/MEMORY.md`
- **Index for search:** After adding substantive content, run QMD against this folder
  (see root prompt: `qmd collection`, `qmd embed`, then `qmd query` / `qmd search`).
- **Read back:** Prefer `qmd query "…"` or `qmd search "…" --json` over reading this
  whole file when the topic is broad.

---

*(Entries below.)*
