# `todoist` — personal Todoist CLI

Personal CLI for Dima's Todoist workspace. **Optimised for AI agents:**
default output is tab-separated compact lines so an LLM can parse it
without burning tokens on JSON whitespace. A human can read it too.

**What this is not.** No labels, no sections, no full-text search, no
saved filters, no team/shared workspaces, no reminders, no attachments,
no offline cache, no TUI/colour, no pagination. Personal account,
single user, macOS host. See PRD §11 for the full out-of-scope list.

---

## Auth setup

Get a token: app.todoist.com → Settings → Integrations → Developer.

Either:

```sh
export TODOIST_TOKEN=...
```

Or persist it (mode `0600`):

```sh
echo "$TOKEN" | todoist auth login
```

The CLI never accepts the token as a flag (would leak via shell history
and `ps`). Token is never printed to stdout, stderr, logs, or
`--version` output.

---

## Output schema (the stable agent contract)

`--json` is a raw Todoist API passthrough and is **explicitly unstable**.
Bind long-lived parsers to the compact format below.

**Free-text whitespace normalisation** (project names, task content): all
whitespace runs are collapsed to a single space, then trimmed. Comment
bodies in `task get` instead escape `\n`/`\t` literally so each comment
stays on one line.

### Tasks — 6 columns, tab-separated

```
<id>	<due>	<p>	<project>	<parent>	<content>
```

| Column   | Format                                               | Empty      |
|:---------|:-----------------------------------------------------|:-----------|
| id       | numeric Todoist id                                   | always set |
| due      | `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`                   | `-`        |
| p        | `p1` / `p2` / `p3` / `p4` (UI semantics)             | `p4`       |
| project  | project name, whitespace-normalised                  | always set |
| parent   | parent task id for sub-tasks                         | `-`        |
| content  | task content, whitespace-normalised                  | always set |

Example:

```
9876543210	2026-05-12	p1	Inbox	-	Buy milk
9876543211	-	p3	Inbox	-	Reply to Anna
9876543212	2026-05-09	p1	Side project: book	-	Ship PRD draft
```

### Projects — 2 columns

```
<id>	<name>
```

### `task get` — header block + comments

```
id	9876543210
content	Ship PRD draft
project	6cV9abc	Side project: book
parent	-
due	2026-05-09
priority	p1
url	https://todoist.com/showTask?id=9876543210
created	2026-05-01T10:23:00Z
comments	2
--
4321	2026-05-08T12:00:00Z	First draft pushed
4322	2026-05-09T09:00:00Z	Need PO sign-off
```

If `comments` is `0`, the `--` and everything below are omitted.

### Comments (in `task get`) — 3 columns

```
<comment_id>	<posted_at>	<content>
```

`posted_at` is ISO-8601 UTC. Newlines/tabs in `content` are escaped as
`\n` / `\t` so each comment stays on one line.

### Errors

Single line on stderr, prefixed `error:`. Exit codes: `0` ok, `1`
generic, `2` usage, `3` auth, `4` not-found, `5` network, `6`
rate-limited.

### Priority semantics

The CLI uses **UI** numbering everywhere: `1` is urgent, `4` is lowest.
The Todoist API uses the inverse — the CLI handles the inversion.

---

## Agent recipes

```sh
# What should I do now? (overdue + today + no-due, top 5)
todoist task ls --limit 5

# Capture a task in Inbox, urgent, due tomorrow.
todoist task add "Reply to Anna" --due tomorrow --priority 1

# Full context on one task before acting.
todoist task get 9876543210

# Postpone everything overdue to tomorrow.
todoist task ls --due overdue | cut -f1 | xargs -I{} todoist pp {} tomorrow

# Leave a multi-line progress note.
echo "Pushed first draft.\nWaiting on review." | todoist task comment 9876543210 -

# Look ahead at the week.
todoist task ls --due thisweek
```

For full flag syntax run `todoist <cmd> --help`.

---

## Install

```sh
pipx install git+https://github.com/dima/TodoistMCP.git
```
