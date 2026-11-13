# TechRadar — Workflow & Implementation Guide

TechRadar automatically builds a [Thoughtworks Build Your Own Radar](https://radar.thoughtworks.com) from the components recorded in Dependency-Track. A Jenkins pipeline dumps all components, lets an AI agent decide the blips (grouping, quadrant, ring), validates those decisions, and emits `radar.json`.

- Radar : https://radar.thoughtworks.com/?documentId=https%3A%2F%2Fraw.githubusercontent.com%2FJesen0307%2FTechRadar%2Frefs%2Fheads%2Fmain%2Fradar.json

## Repository layout

| File / dir | Role |
|---|---|
| `Jenkinsfile` | Orchestrates the whole run (checkout → dump → agent → validate → build). |
| `dtrack_dump.py` | Fetches all components from Dependency-Track and writes the agent input. |
| `radar-playbook.md` | Operating instructions the AI agent must follow to decide blips. |
| `blips.json` | Agent input **and** output: the previous run's blips, updated in place. Committed to the repo. |
| `build_radar.py` | Validates `blips.json` against the component dump and emits `radar.json` + `changes.md`. |
| `radar.json` | Generated radar document rendered by Thoughtworks Radar. |
| `dump/` | Generated working data (`projects.json`, `components.json`, per-project dumps). Not committed. |

---

## End-to-end workflow

```
Dependency-Track
      │  (REST API, X-Api-Key)
      ▼
dtrack_dump.py ──► dump/projects.json
                   dump/components.json        (unique components, agent input)
                   dump/components/<proj>.json (raw, per project)
      │
      ▼
AI agent (OpenCode, reads radar-playbook.md)
      │  reads blips.json (previous run) + dump/components.json
      ▼
blips.json  (updated in place: blips + excluded)
      │
      ▼
build_radar.py --check          (validate; aborts on error)
      │
      ▼
build_radar.py --out radar.json --changes changes.md
      │
      ▼
radar.json  ──► Thoughtworks Radar   (artifacts archived by Jenkins)
```

### Jenkins stages (`Jenkinsfile`)

1. **Checkout** — `checkout scm`, then clean stale outputs (`dump`, `radar.json`, `changes.md`, `blips.previous.json`).
2. **Read previous blips** — if `blips.json` is missing, seed it with `{"blips": [], "excluded": []}` (first run). Copy it to `blips.previous.json` as the immutable snapshot used for `isNew` comparison.
3. **Prepare tools** — verify `python3` and `curl`; if `RUN_AGENT=true` and OpenCode is absent, install it into `.tools/bin`.
4. **Fetch all components** — run `dtrack_dump.py` (optionally scoped by `TAG`) using the `dtrack-api-key` credential.
5. **Agent decides blips** — run the OpenCode `aiAgent` with `radar-playbook.md`; it rewrites `blips.json`. Failures are caught and marked `FAILURE` without failing the build (`failOnAgentError: false`).
6. **Validate blips** — `build_radar.py --check` (fails the build on invalid output).
7. **Build radar** — `build_radar.py` writes `radar.json` and `changes.md`.

**Post:** archive `radar.json`, `blips.json`, `blips.previous.json`, `changes.md`, `dump/components.json`, `dump/projects.json` (plus all of `dump/**` when `ARCHIVE_RAW=true`).

### Pipeline parameters

| Parameter | Default | Meaning |
|---|---|---|
| `DT_URL` | `http://dependency-track-apiserver-1:8080` | Dependency-Track API server base URL. |
| `TAG` | *(empty)* | Only include projects carrying this tag. Validated against `[A-Za-z0-9_.-]+`. |
| `RUN_AGENT` | `true` | Run the AI agent; `false` reuses the committed `blips.json`. |
| `ARCHIVE_RAW` | `false` | Archive the full raw `dump/**` tree. |

---

## Implementation prerequisites

### 1. Dependency-Track
- A running Dependency-Track API server reachable from the Jenkins node.
- Projects uploaded/analyzed so components and (optionally) findings exist.
- An API key with at least **`VIEW_PORTFOLIO`** permission. Missing permission surfaces as `401/403`.

### 2. Jenkins
- A Pipeline job pointing at this repository (`checkout scm`).
- The **`aiAgent`** plugin available (provides `aiAgent agent: openCode()` and `yoloMode`).
- Agent executors with `python3` (3.8+) and `curl`. OpenCode is auto-installed into `.tools/bin` when missing, so outbound network access to `https://opencode.ai` is required unless OpenCode is pre-installed on the node.
- Credentials:
  - `dtrack-api-key` — string credential exposed as `DT_KEY` (must match the env var `dtrack_dump.py` reads).
  - `OpenCode` — API credentials for the agent (id `OpenCode`).
- No concurrent builds (`disableConcurrentBuilds`) because the job mutates the committed `blips.json`.


### 3. Runtime environment variables

| Variable | Used by | Purpose |
|---|---|---|
| `DT_KEY` | `dtrack_dump.py` | Dependency-Track API key (required; `dtrack_dump.py` exits if unset). |
| `DT_URL` | `dtrack_dump.py`, Jenkins | Base URL of the API server (default `http://localhost:8082` locally). |

---

## Notes & constraints

- **`blips.json` is the only file the agent may write.** It must be valid JSON with exactly two keys, `blips` and `excluded`, and no markdown or trailing text.
- **Every component id must appear exactly once**, in a blip or in `excluded`; `build_radar.py` rejects and fails the build otherwise.
- **`isNew` is recomputed each run** against `blips.previous.json`; the values stored in the committed `blips.json` are stale.
- The radar `description` is auto-generated from component names — the agent's `reason` field is an audit trail only and is not shown on the radar.
- **A missing findings field is not proof of safety.** If the Dependency-Track analyzer is inactive, the playbook requires lowering confidence and noting it in `reason`.
