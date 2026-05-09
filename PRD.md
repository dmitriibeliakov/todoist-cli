# PRD: `todoist` Personal CLI

**Owner:** Dima Beliakov (beliakov@cteleport.com)
**Status:** Draft v3 (agent-tailored)
**Date:** 2026-05-09
**Repo path:** `/Users/dima/TodoistMCP`

---

## 1. Goal

Provide a clean, scriptable command-line surface for managing Dima's
**personal Todoist workspace**, designed first and foremost as a tool that
**AI agents can call** to figure out what to do next, capture new work, and
update task state.

Two consumer classes, in priority order:

1. **AI agents** (Claude in various wrappers — including the eventual MCP
   server in `TodoistMCP`). Need predictable inputs, structured outputs,
   and **minimal token cost per call**.
2. **Dima at a zsh prompt.** Same surface, just operated by a human.

This is a meaningful inversion from a typical CLI: we are not optimising
for a human reading a wide table of tasks in a terminal. We are optimising
for an LLM consuming the smallest possible string that still contains all
the fields it needs to make a decision.

**Single-user assumption (non-negotiable for v1).** This tool is built for
exactly one user (Dima) on macOS, with one Todoist personal account. There
is no multi-tenant model, no per-user config switching, no profile system,
no "current user" concept. Implementations must not pre-pave scaffolding
for multi-user support — one token, one config file, one workspace.

### Non-goals (v1) — confirmed out of scope

1. No team / shared / collaborator workspaces. Personal account only.
1. No labels, no sections.
1. No saved searches, no Todoist filter expression language, no full-text
   search. Listing supports a small fixed set of named filters only
   (project, due bucket, priority).
1. No reminders, no file attachments.
1. No recurring-task rule editing beyond `due_string` pass-through.
1. No interactive TUI, no colour, no spinners.
1. No offline cache / sync engine. Every command is a live API call.
1. No MCP server in this PRD (planned v1.1; the CLI core is factored to
   make that wrapper trivial).

### In scope (v1) — capabilities and priority

| Capability                          | Priority | Notes                                                  |
|:------------------------------------|:---------|:-------------------------------------------------------|
| List tasks (with simple filters)    | **P0**   | Primary agent-discovery surface                        |
| List projects                       | **P0**   | Agents need project IDs and names to reason            |
| Get one task with comments          | **P0**   | Agents need full context before acting on a task       |
| Create task                         | **P0**   | Quick capture (most-frequent human action)             |
| README.md as agent bootstrap doc    | **P0**   | First thing an agent reads; ships in the repo          |
| Postpone task                       | P1       |                                                        |
| Set priority                        | P1       |                                                        |
| Complete task                       | P1       |                                                        |
| Delete task                         | P1       |                                                        |
| Add comment to task                 | P1       | Promoted from P2 — agents will leave progress notes    |
| Create sub-task                     | P1       | `--parent` on `task add`                               |
| Create project                      | P2       | Infrequent                                             |

P0 ships first and is polished hardest. P1 ships in v1. P2 ships in v1 if
cheap, otherwise v1.1.

---

## 2. Personas

### Persona A — AI agent (primary)

- Calls the CLI via shell from a Claude session or a future MCP wrapper.
- Token-budget conscious. Every output line eaten by the agent costs both
  money and context-window space.
- Prefers structured, fixed-field output it can split on whitespace or
  tabs. Will only fall back to JSON when it needs fields the compact
  format omits (mainly comments and full metadata).
- Cannot recover from ambiguous output. Field order must be stable; null
  fields must have a consistent placeholder (`-`).
- Will retry on transient errors but not on logic errors. Exit codes
  matter as much as stdout.

### Persona B — Dima at the terminal (secondary)

- Lives in zsh. Runs the CLI manually for quick captures and one-off edits.
- Tolerates the agent-tailored output shape — it's still scannable.
- Will pipe `--json` to `jq` when he needs more.

### Pain points the v1 must address

1. **Agents have no native way to read or write Todoist** without
   hand-rolling REST calls in every session. Predictable primitives in
   one place fix this.
2. **Agents can't afford verbose output.** A 50-task project listed in raw
   Todoist JSON is several thousand tokens; the same listing in compact
   line format is a fraction of that.
3. **Capture friction in the web/app/mobile** — losing thoughts when
   not at a Todoist surface.

---

## 3. API choice

Use the **Todoist unified API v1**, REST-style endpoints
(`https://api.todoist.com/api/v1/...`).

Reason: simpler request/response than the Sync API, single round-trip per
action, covers everything in scope. The Sync API only earns its keep with
batching / offline / full-state diffs, none of which apply.

**Pinned constant.** The base URL and version are pinned in code as a
single constant: `TODOIST_API_BASE = "https://api.todoist.com/api/v1"`.
On v1 sunset, this CLI is end-of-life until updated.

### Endpoint reference (verified 2026-05)

| Capability         | Method   | Path                  | Key fields                                              |
|:-------------------|:---------|:----------------------|:--------------------------------------------------------|
| List projects      | `GET`    | `/projects`           | —                                                       |
| Create project     | `POST`   | `/projects`           | `name`, `color`                                         |
| List tasks         | `GET`    | `/tasks`              | `project_id` filter (server-side)                       |
| Get task           | `GET`    | `/tasks/{id}`         | —                                                       |
| Create task        | `POST`   | `/tasks`              | `content`, `project_id`, `parent_id`, `due_string`, `priority` |
| Update task        | `POST`   | `/tasks/{id}`         | any subset of create fields                             |
| Delete task        | `DELETE` | `/tasks/{id}`         | —                                                       |
| Complete task      | `POST`   | `/tasks/{id}/close`   | —                                                       |
| List comments      | `GET`    | `/comments`           | `task_id`                                               |
| Add comment        | `POST`   | `/comments`           | `task_id`, `content`                                    |

The `--due overdue|today|thisweek` filters are computed **client-side**
from the `due.date` returned per task. Reason: the v1 endpoint's
server-side filter takes a Todoist filter expression which is out of scope
to support, and the per-project task list is small enough that
client-side filtering is fine.

### Auth

Personal API token from `app.todoist.com` → Settings → Integrations →
Developer. Sent as `Authorization: Bearer <token>`. Tokens do not expire.

### Priority semantics

Todoist's API priority is **inverted** vs. its UI:

| UI label | API value |
|:---------|:----------|
| p1       | 4         |
| p2       | 3         |
| p3       | 2         |
| p4       | 1         |

**The CLI exposes UI semantics everywhere** (input flag and output token).
`--priority 1` is urgent; output reads `p1`. The CLI does the inversion.
Agent-facing docs (`--help`) state this in one line so the LLM caller
doesn't need to remember the API's inversion.

### Due date input

`due_string` accepts natural language: `"today"`, `"tomorrow"`,
`"next monday"`, `"in 3 days"`, `"jan 15"`, `"2026-06-01"`. Pass through
verbatim. If input matches `^\d{4}-\d{2}-\d{2}$`, send as `due_date` to
bypass NL parsing.

### Rate limits

API v1 enforces per-15-minute windows; on `429` the CLI surfaces the error
and exits non-zero. No retry/backoff in v1.

---

## 4. Setup & auth

### Token storage (precedence)

1. `TODOIST_TOKEN` env var.
1. `~/.config/todoist-cli/config.toml` (mode `0600`):

   ```toml
   token = "abc123..."
   default_project = "Inbox"
   ```

1. Otherwise: `error: no token. set TODOIST_TOKEN or run 'todoist auth login'`. Exit 3.

### `todoist auth login`

Reads token from stdin (or prompt if TTY), validates via `GET /projects`,
writes the config file with `0600`. No browser flow.

### Token security rule (non-negotiable)

The token must never appear in any output the binary produces — not on
stdout, not on stderr, not in error messages, not in `--version`, not in
log files, not in stack traces. Any error path that includes a request
URL or headers must redact the `Authorization` header. The arg parser
must not accept the token as a positional / `--token` flag (which would
leak it into shell history and `ps`).

---

## 5. Output formats

This section is the heart of the PRD. **Output design is a first-class
feature**, not a presentation detail.

### 5.1 Default format — compact, line-oriented

One record per line. Tab-separated fixed fields. No headers. No colour.
Stable column order across versions (additions append; never reorder, never
re-purpose).

**Cross-cutting rule — free-text whitespace normalisation.** In every
tabular output (`task ls`, `proj ls`, the §5.2 header block, any compact
single-line success echo), all free-text fields sourced from
user-supplied data — project names, task content, comment bodies in the
`task get` comment block, and any future user-supplied string field —
have all whitespace runs (including newlines and tabs) collapsed to a
single space, then trimmed. This rule is what makes the tab-delimited
format unambiguously parseable. Comment bodies in §5.2 are the one
exception: see §5.2 for their `\n`-escaping rule (which serves the same
goal — one record per line).

**Tasks** — 6 columns (`\t`-separated), always:

```
<id>	<due>	<p>	<project>	<parent>	<content>
```

Where:

| Column      | Format                                              | Placeholder when empty |
|:------------|:----------------------------------------------------|:-----------------------|
| `id`        | opaque string ID assigned by Todoist (alphanumeric) | (always present)       |
| `due`       | `YYYY-MM-DD` (or `YYYY-MM-DDTHH:MM` if time set)    | `-`                    |
| `p`         | `p1` / `p2` / `p3` / `p4` (UI semantics)            | `p4`                   |
| `project`   | project name; whitespace-normalised per cross-cutting rule | (always present) |
| `parent`    | parent task id for sub-tasks, else `-`              | `-` (top-level)        |
| `content`   | task content; whitespace-normalised per cross-cutting rule | (always present) |

The `parent` column is always emitted. Top-level tasks render `-`. Agents
that don't care about hierarchy can ignore column 5 and take everything
from column 6 to EOL as content; agents that need hierarchy reconstruct
it from column 5 without a second call.

Example (3-task agent listing — top-level tasks, so `parent` is `-`):

```
9876543210	2026-05-12	p1	Inbox	-	Buy milk
9876543211	-	p3	Inbox	-	Reply to Anna
9876543212	2026-05-09	p1	Side project: book	-	Ship PRD draft
```

**Projects** — 2 columns (project name whitespace-normalised per the cross-cutting rule):

```
<id>	<name>
6cV9xyz	Inbox
6cV9abc	Side project: book
```

**Comments** (in `task get` output) — 3 columns:

```
<comment_id>	<posted_at>	<content>
```

`posted_at` is ISO-8601 UTC. Comment content escapes newlines as `\n`
(literal backslash-n) and tabs as `\t` so each comment stays on exactly
one line and the column delimiter is unambiguous. This is the one
deviation from the §5.1 cross-cutting collapse-to-space rule, made so
that callers can losslessly recover comment line breaks if needed.

### 5.2 `task get` format

Token-efficient single-task view. No JSON wrapper. Fixed field order:

```
id	9876543210
content	Ship PRD draft
project	6cV9abc	Side project: book
parent	-
due	2026-05-09
priority	p1
url	https://todoist.com/showTask?id=9876543210
created	2026-05-01T10:23:00.123456Z
comments	2
--
4321	2026-05-08T12:00:00.000000Z	First draft pushed
4322	2026-05-09T09:00:00.791617Z	Need PO sign-off on §11
```

Two `\t`-separated columns above the `--` separator (key, value(s)). Below
the separator, comments in the same compact format as §5.1. If the task
has no comments, the `--` and everything below are omitted; `comments` is
`0`.

This format costs ~10 lines for a fully-loaded task with two comments —
roughly an order of magnitude fewer tokens than the equivalent raw JSON.

### 5.3 `--json` — raw API escape hatch (UNSTABLE)

When an agent or the user needs fields the compact format omits, pass
`--json`. Output is the raw Todoist API response (object or array),
unmodified, no wrapping, no pretty-printing. Newline at EOF only.

**Stability:** `--json` output is **explicitly unstable** — its shape is
whatever Todoist's API returns today and may change with no notice if
Todoist evolves their API. **The §5.1 / §5.2 compact line format is the
stable agent contract.** Agents that need long-lived parsers should bind
to the compact format; `--json` is for ad-hoc human inspection or
agent-to-agent passthrough where the consumer already understands the
Todoist schema.

The README states this clearly so agent authors don't accidentally build
on `--json` and break when Todoist ships a v2.

### 5.4 `--quiet`

Suppress success messages from mutating commands. Errors still go to
stderr. Useful for shell scripts that only check exit code.

### 5.5 What the default is *not*

- Not pretty-printed JSON. (~3× the tokens for the same data.)
- Not a table with aligned columns or a header row. (Headers are noise to
  an LLM that's been told the schema in `--help`.)
- Not coloured. ANSI escapes leak tokens and confuse some agent harnesses.
- Not paginated. Personal workspaces are small; we list all matches.

### 5.6 Errors

Single line on stderr, prefixed `error:`. Non-zero exit. No stack traces,
no "did you mean" suggestions, no usage dumps unless the user passed
`--help`.

### 5.7 Exit codes

| Code | Meaning                                   |
|:-----|:------------------------------------------|
| 0    | success                                   |
| 1    | generic error / API 4xx other than below  |
| 2    | usage error (bad flags, missing arg)      |
| 3    | auth error (no token, 401, 403)           |
| 4    | not found (404)                           |
| 5    | network error (DNS, timeout, no internet) |
| 6    | rate limited (429)                        |

---

## 6. Command surface

Top-level binary: `todoist`. Verb-noun, with short aliases for the
common-from-the-shell cases. Agents may use either form; we test both.

| Command                                                        | Alias       | Capability                  | Priority |
|:---------------------------------------------------------------|:------------|:----------------------------|:---------|
| `todoist task ls [filters]`                                    | `ls`        | List tasks (compact)        | **P0**   |
| `todoist task get <id>`                                        | `get`       | Get one task + comments     | **P0**   |
| `todoist task add <content> [flags]`                           | `add`       | Create task / sub-task      | **P0**   |
| `todoist project ls`                                           | `proj ls`   | List projects (compact)     | **P0**   |
| `todoist task postpone <id> <due>`                             | `pp`        | Reschedule task             | P1       |
| `todoist task pri <id> <1-4>`                                  | —           | Set priority                | P1       |
| `todoist task done <id>`                                       | `done`      | Complete task               | P1       |
| `todoist task rm <id>`                                         | `rm`        | Delete task                 | P1       |
| `todoist task comment <id> <text>`                             | —           | Add comment                 | P1       |
| `todoist project add <name> [--color]`                         | `proj add`  | Create project              | P2       |
| `todoist auth login`                                           | —           | Save token                  | P1       |

Global flags: `--json`, `--quiet`, `--help`, `--version`.

### 6.1 `task ls` — **P0**

> As an agent, I want to retrieve outstanding tasks in a low-token format
> so I can decide what to do next without burning context budget.

**Filters** (all optional, all combinable, AND-semantics):

| Flag                  | Values                                                   |
|:----------------------|:---------------------------------------------------------|
| `--project <name|id>` | exact (case-insensitive) name or id                      |
| `--due <bucket>`      | `overdue` / `today` / `thisweek` / `none` / `future` / `all` |
| `--priority <1-4>`    | UI semantics; agent passes `1` for urgent                |
| `--limit <N>`         | positive integer; truncates output to first N rows after sort. Default: no limit. |

Bucket meanings (computed in the host system timezone — i.e. wherever the
MCP server / CLI is running):

- `overdue` — `due.date < today`
- `today` — `due.date == today`
- `thisweek` — `due.date` in `[today, today+7]` inclusive
- `none` — task has no due date
- `future` — `due.date > today` (everything coming up later)
- `all` — disable due-date filtering entirely

**Default with no `--due` flag: `overdue` + `today` + `none`.** This
matches the agent's most common question — "what should I do *now*?" —
without flooding the response with future-dated work. Agents that want
to look ahead pass `--due thisweek` or `--due future`; agents that want
the unfiltered backlog pass `--due all`.

Sort order (stable, documented): `due ASC` (no-due last), then
`priority ASC` (p1 first), then `id ASC`. First line = top candidate.

`--limit N` is applied **after** the sort, so `--limit 5` reliably
returns the top 5 candidates. Directly serves the agent token-budget
thesis — three lines of code, big payoff.

**Output:** §5.1 task format.

### 6.2 `task get` — **P0**

> As an agent, I want full context on a single task — including its
> comments — in one round-trip and one parseable blob.

**Invocation:** `todoist get 9876543210`

**Output:** §5.2 format. Internally, this is two API calls (`GET /tasks/{id}`
+ `GET /comments?task_id={id}`) merged into one output blob; the agent
pays for one CLI call.

### 6.3 `task add` — **P0**

> As an agent or human, I want to create a task with optional due date,
> priority, project, and parent in one predictable invocation.

```
todoist add "Buy milk"
todoist add "Buy milk" --due tomorrow --priority 1 --project Inbox
todoist add "Sub-step A" --parent 9876543210
```

Flags:

| Flag          | Short | Value                                       |
|:--------------|:------|:--------------------------------------------|
| `--due`       | `-d`  | natural-language string or ISO date         |
| `--priority`  | `-p`  | `1`–`4` (UI semantics)                      |
| `--project`   | `-P`  | project name (case-insensitive) or id       |
| `--parent`    | —     | parent task id (creates a sub-task)         |

Default project: `default_project` from config, else Inbox.

**Output (default, single line — same task schema as `task ls`, useful for chaining):**

```
9876543210	2026-05-10	p1	Inbox	-	Buy milk
```

This means an agent can do `id=$(todoist add "X" | cut -f1)` trivially.

### 6.4 `project ls` — **P0**

```
todoist proj ls
```

**Output:** §5.1 project format.

### 6.5 Mutating P1 commands

Each emits one terse stdout line on success (suppressible with `--quiet`),
echoing the same compact task schema where applicable so that an agent
parsing output gets the post-mutation state without a follow-up call.

| Command                              | Success stdout                              |
|:-------------------------------------|:--------------------------------------------|
| `todoist pp <id> <due>`              | full task line (§5.1) reflecting new due   |
| `todoist task pri <id> N`            | full task line reflecting new priority     |
| `todoist done <id>`                  | `done\t<id>`                                |
| `todoist rm <id>`                    | `deleted\t<id>`                             |
| `todoist task comment <id> <text>`   | `<comment_id>\t<posted_at>`                 |

`task comment` accepts `-` for `<text>` to read the body from stdin
(useful for multi-line agent-written notes).

### 6.6 `project add` — P2

```
todoist project add "Side project: book" [--color berry_red]
```

**Output:** project line (§5.1): `<id>\t<name>`.

---

## 6.7 Documentation strategy: README vs `--help`

The CLI ships with two documentation surfaces, with strict roles to keep
them from drifting:

**`--help` is the single source of truth for syntax** — command list,
flags, argument shapes, exit codes. Generated by the arg parser; cannot
drift from the binary. Each subcommand's `--help` also documents the
priority inversion / due-string rules that apply to that command.

**README.md is the single source of truth for the *contract*** — the
parts agents memorise and parse against:

1. One-paragraph "what this is and is not" (sets scope so agents don't try labels/search/sections).
2. **The full output schema** (§5 of this PRD, copied verbatim and kept in sync). This is the stable parsing contract.
3. **Agent recipes** — 4–6 worked examples, e.g. "find what to do next", "capture a quick task", "postpone everything overdue", "leave a progress note on a task".
4. Auth setup (token env var or `auth login`).
5. A pointer line: *"For full flag syntax run `todoist <cmd> --help`."*

README never re-lists flags. Flag renames update `--help` automatically
(arg parser re-runs); the README only needs review when the *contract*
changes (output schema, scope, recipes), which is exactly when human
review is warranted.

### Anti-staleness mechanics

- Snapshot test in CI: runs every `--help`, diffs against goldens. Failures show up in PR review.
- Output-schema regression test: an integration test parses `task ls`, `task get`, etc. with the schema documented in the README. If output drifts, the test fails before the README does.
- README has no flag tables. Tempting, but the moment you copy them, they're stale.

### Token budget for agent bootstrap

An agent's first session-call should be: read README (~few hundred
tokens), then call `todoist <cmd> --help` only for the specific command
it's about to use. The README is hard-capped at ~150 lines so this stays
cheap.

---

## 7. Error handling

| Scenario                              | Behaviour                                                                  |
|:--------------------------------------|:---------------------------------------------------------------------------|
| Project name doesn't exist            | `error: project "Foo" not found`. Exit 4.                                  |
| Project name matches multiple         | `error: project "x" is ambiguous (3 matches); use --project <id>`. Exit 2. |
| Task id doesn't exist                 | `error: task <id> not found`. Exit 4.                                      |
| Network failure                       | `error: network: <message>`. Exit 5. No retry.                             |
| 401 / invalid token                   | `error: auth failed; check token`. Exit 3.                                 |
| 429 rate limit                        | `error: rate limited; retry after Ns`. Exit 6.                             |
| Bad priority / due bucket             | Exit 2 with one-line usage hint. Validated client-side.                    |
| Bad due string (API rejects)          | Surface API error message verbatim. Exit 1.                                |
| Parent id doesn't exist (sub-task)    | Surface API 404. Exit 4.                                                   |

Project-name resolution caches the project list **in memory** for the
duration of a single command. Not persisted to disk in v1.

---

## 8. Acceptance criteria

Each criterion ties back to a confirmed pain point or to agent-readiness.

### 8.1 `task ls` (P0)

1. With no flags, returns all outstanding (non-completed) tasks across all projects. **Completed tasks are out of scope for `task ls` in v1** — there is no `--completed` flag and no plan to add one. Agents that need historical completion data can use `--json` against a future endpoint or wait for v1.1.
1. Output uses the §5.1 task schema exactly: 6 tab-separated fields, one task per line, no header, no trailing whitespace.
1. `--project "Name"` resolves a project by case-insensitive exact name match; partial matches do not match. *Pain: agent ambiguity.*
1. `--project <numeric-id>` is accepted and bypasses name resolution.
1. `--due today` returns exactly the tasks whose `due.date` is today in local time.
1. `--due overdue` returns tasks whose `due.date < today`.
1. `--due thisweek` returns tasks whose `due.date` is in `[today, today+7]` inclusive.
1. `--due none` returns tasks with no due date.
1. `--priority N` matches UI priority N (the CLI does the inversion).
1. Filters combine with AND semantics.
1. Sort order is `due ASC, priority ASC, id ASC`. No-due tasks sort last.
1. `--json` emits the raw `GET /tasks` array (after applying filters).
1. `--limit N` truncates output to the first N rows after sort. `--limit 0` and negative values exit 2. Default (no flag) is no limit.
1. Empty result prints nothing on stdout, exits 0.

### 8.2 `task get` (P0)

1. Output matches the §5.2 schema exactly: header block, `--`, comments.
1. `comments` line shows the integer count.
1. If `comments` is `0`, the `--` separator and comment lines are omitted.
1. Newlines in comment bodies are escaped as `\n` so each comment is one line.
1. `--json` emits a single object `{"task": {...}, "comments": [...]}`.
1. Non-existent id exits 4.

### 8.3 `task add` (P0)

1. With no flags, creates a task in the default project (config) or Inbox.
1. `--due "tomorrow"` produces a task whose `due.date` is tomorrow's local date.
1. `--priority 1` produces a task with API priority `4` (urgent in UI).
1. `--project "Name"` resolves by case-insensitive exact name match.
1. `--parent <id>` creates a sub-task; output's `parent` column is `<id>`.
1. Stdout on success is exactly one line in the §5.1 task schema.
1. `--json` emits the raw API response.
1. Missing/invalid token exits 3 *before* making any network call.

### 8.4 `project ls` (P0)

1. Lists all projects, one per line, `<id>\t<name>`.
1. No header, no colour, no extra columns.
1. `--json` emits the raw API array.

### 8.5 P1 mutating commands

1. `pp <id> <due>`, `task pri`, and (when applicable) succeed with exit 0 and emit a full §5.1 task line on stdout, allowing chaining.
1. `done <id>` emits `done\t<id>`. For recurring tasks, the task remains and its `due` advances per Todoist rules.
1. `rm <id>` emits `deleted\t<id>`, no confirmation prompt.
1. `task comment` accepts `-` for stdin input; emits `<comment_id>\t<posted_at>`.
1. All P1 mutations honour `--quiet` (no stdout on success) and `--json` (raw API).
1. Non-existent ids exit 4.

### 8.6 `project add` (P2)

1. Returns exit 0 and prints `<id>\t<name>`.
1. Invalid `--color` exits 2 before any API call.
1. `--json` emits the raw response.

### 8.7 README and `--help` (P0)

1. README.md exists at the repo root, ≤ 150 lines.
1. README contains: a one-paragraph "what this is/isn't", the full output schema from §5, auth setup, 4–6 agent recipes, and a pointer to `todoist <cmd> --help` for flag syntax.
1. README does **not** duplicate flag listings — those live only in `--help`.
1. Every subcommand has a non-empty `--help` that documents its flags, exit codes, and any semantics relevant to that command (priority inversion on commands that accept `--priority`; due-string examples on commands that accept due dates).
1. CI snapshot test: `--help` outputs are diffed against goldens.
1. CI integration test: parses the documented output schema for `task ls`, `task get`, `proj ls`, `task add`. Fails if real output drifts from the schema in README.

### 8.8 Cross-cutting

1. All commands support `--json` and `--quiet`. The two flags are independent: `--json` controls output format; `--quiet` suppresses success messages from mutating commands. There is no special-case interaction — `--json` is already silent on success-without-data and routes errors to stderr, so `--quiet` has nothing to additionally suppress when `--json` is set.
1. All commands handle 401 / 404 / 429 / network errors per §7.
1. `~/.config/todoist-cli/config.toml` is created with mode `0600`.
1. `--help` on any subcommand documents the priority inversion, due-string examples, and the schema of any output the command produces.
1. The core (API client, models, command logic) is factored as a reusable package — *not* inlined in `main` — so the v1.1 MCP server can import it without refactor.
1. **Token-budget acceptance:** A `task ls` of 50 tasks emits ≤ ~3 KB of output (default format). The same listing with `--json` is materially larger; this is documented.

---

## 9. Resolved questions (from discovery)

| Question                              | Resolution                                                |
|:--------------------------------------|:----------------------------------------------------------|
| Top P0 capability?                    | Tied: `task ls`, `task get`, `task add`, `project ls`     |
| Should `done` ship in v1?             | Yes                                                       |
| Comments in v1?                       | Yes — promoted to P1 (agents will leave progress notes)   |
| Sub-tasks in v1?                      | Yes — `--parent` on `task add`; `parent` column in `ls`   |
| Listing / filters in v1?              | Yes for fixed named filters; no for query language        |
| Labels / sections?                    | No                                                        |
| Reminders / attachments?              | No                                                        |
| Natural-language one-liner parsing?   | No — explicit flags                                       |
| Default output format?                | Tab-separated compact lines, agent-tailored               |
| Default colour / pretty printing?     | None                                                      |
| MCP wrapper relationship              | Primary motivator; CLI core must be MCP-reusable          |
| Implementation language?              | **Python** (see §12 for package layout and distribution)  |
| Timezone for `--due` filters?         | System timezone of the host running the binary (i.e. wherever the MCP server is deployed). No override flag in v1. |
| Default scope of `task ls` (no flags)?| `overdue` + `today` + `none` (no-due-date). Use `--due thisweek` / `--due all` to broaden. |
| `--json` stability promise?           | **Unstable.** `--json` is a raw-API passthrough. The §5.1/§5.2 compact line format is the stable agent contract. |
| Token security?                       | Token never appears in any output the binary produces (stdout, stderr, logs, `--version`, error traces). Config file is `0600`. |
| Multi-line task content / comments?   | `task ls`: collapse newlines and tabs in `content` to single spaces. `task get`: escape newlines in comment bodies as literal `\n`. |

---

## 10. Open questions

1. **Project resolution: cache to disk?** ~50 ms per `GET /projects` per command adds up if agents call the CLI in tight loops. Cache to `~/.cache/todoist-cli/projects.json` with a short TTL (e.g. 5 min)? Recommendation: defer to v1.1 unless the lag is annoying.
1. **`task ls` — cap on result count?** Reasonable to cap default-listing at e.g. 200 tasks with a stderr-warning on truncation? Personal workspaces rarely exceed ~200 active tasks. Recommendation: no cap in v1 (agents wanting a hard ceiling can pass `--limit`).
1. **Should the task schema include `created_at` or `url`?** Helpful for some agent workflows; costs ~30 chars per row. `task get` already exposes both. Recommendation: keep `task ls` minimal.

---

## 11. Out of scope (explicit "won't do")

Do not pre-pave hooks, flags, or scaffolding for any of these:

- Labels, sections.
- Saved searches, full-text search, Todoist filter expression language.
- Reminders, file attachments.
- Recurring-rule editing beyond `due_string` pass-through.
- Bulk operations, undo, karma view.
- Team / shared / collaborator workspaces, assignees, sharing.
- Offline cache / sync engine.
- TUI, ANSI colour, table-formatted output, pagination.
- Homebrew formula, auto-update.

### v1.1 candidates (not committed)

- **MCP server** wrapping the same core package — the actual end goal.
  Transport: **stdio** (Claude Desktop-style). Stdio keeps `commands.*`
  synchronous and free of asyncio plumbing — the MCP server is the only
  async surface, and it calls into sync `commands.*` functions directly.
  This matches the single-user / single-host assumption (§1) and avoids
  pulling in HTTP/SSE server frameworks just to talk to one agent.
- Project list disk cache.
- Shell completions.
- `task ls --since <date>`.
- Full-text search if real agent workflows demand it.

---

## 12. Implementation: package layout, distribution, testing

### 12.1 Language and runtime

**Python 3.11+.** Chosen for the v1.1 MCP-server reuse story:

1. The Python MCP SDK is mature and production-ready (v1.26+, Jan 2026).
   (The TypeScript SDK is the reference implementation; Python is a
   first-class peer, not a derivative — both ship from the official MCP
   org and track the spec in lockstep.)
2. The official Todoist SDK (`todoist-api-python`) is Python-native and
   actively maintained by Doist, removing the need to hand-roll the HTTP
   client.
3. The v1.1 MCP server can `import todoist_cli.commands` directly with
   zero process-boundary overhead — no subprocess, no JSON serialization
   round-trip, no separate runtime to manage.

### 12.2 Package layout

```
TodoistMCP/
├── pyproject.toml
├── README.md                          # agent bootstrap doc (§6.7)
├── src/
│   └── todoist_cli/
│       ├── __init__.py
│       ├── client.py                  # HTTP client; one method per API capability; returns typed objects
│       ├── models.py                  # dataclasses for Task, Project, Comment
│       ├── commands.py                # one function per CLI capability; pure logic; returns structured results
│       ├── formatting.py              # compact line / --json renderers (the §5 contract)
│       ├── filters.py                 # due-bucket math, project-name resolution
│       ├── config.py                  # token loading, config file IO
│       └── cli.py                     # argparse layer; calls commands.* and formatting.*
└── tests/
    ├── unit/
    └── integration/
```

**Boundary contract for v1.1 MCP server:** the MCP server imports
`todoist_cli.commands` directly. Each `commands.*` function takes typed
arguments (no argparse `Namespace`), returns typed results, and raises
typed exceptions. The MCP server wraps each function as one MCP tool.
Neither `cli.py` nor `formatting.py` is imported by the MCP server —
those exist only for the human/shell surface.

### 12.3 Distribution

**v1 install path (single supported route):**

```
pipx install git+https://github.com/dima/TodoistMCP.git
```

`pipx` rather than `pip install` because it isolates the CLI's deps from
any other Python the user has. `pipx` is one `brew install pipx` away
on macOS.

PyPI release and Homebrew formula are **v1.1 candidates**, not v1.

### 12.4 Testing strategy

| Layer        | Scope                                                                                    | Where                          |
|:-------------|:-----------------------------------------------------------------------------------------|:-------------------------------|
| Unit         | argparse wiring, output formatters, due-bucket math, priority inversion, config loading  | `tests/unit/`, run on every PR |
| Schema       | parses real CLI output against the §5.1 / §5.2 schema documented in README               | `tests/integration/`, gated on `INTEGRATION=1` |
| Integration  | hits a dedicated Todoist *test* project with a separate token (`TODOIST_TEST_TOKEN`)     | `tests/integration/`, gated on `INTEGRATION=1` |
| `--help` snapshot | every subcommand's `--help` diffed against goldens                                  | `tests/unit/`                  |

**Quality gates (the real ones).** Line coverage is not a target — it
correlates poorly with regression catch-rate at this scale. The two
gates that actually protect the contract are:

1. **Schema-regression test** — parses real CLI output against the §5.1
   / §5.2 schema documented in README. Output drift fails the build.
2. **`--help` snapshot test** — every subcommand's `--help` is diffed
   against goldens. Flag changes surface in PR review.

Unit tests exist to make those two gates fast and to catch logic bugs
in due-bucket math, priority inversion, and config loading. Coverage
percentage is a side-effect, not a target.

**Rate-limit awareness:** integration tests sleep 250 ms between calls
and skip themselves on `429` rather than retry. They are not part of the
default `pytest` invocation.

**No mocking of the Todoist API in v1.** Integration tests run against
the real test project; unit tests use plain function inputs/outputs. A
mock server is more code than it's worth at this scale.

---

## Sources

- [Todoist unified API v1 reference](https://developer.todoist.com/api/v1/)
- [Todoist REST API v2 reference](https://developer.todoist.com/rest/v2/)
- [Find your API token](https://www.todoist.com/help/articles/find-your-api-token-Jpzx9IIlB)
- [Todoist Sync API v9](https://developer.todoist.com/sync/v9/)
