# Deployment

This package ships two binaries:

- `todoist` — interactive CLI for personal use.
- `todoist-mcp` — MCP server (stdio) for delegating restricted access to an agent.

The two share `~/.config/todoist-cli/config.toml` for token + scope.

---

## Delegating to an agent (locked-scope deployment)

Use this when handing the CLI/MCP to an LLM agent that should only touch one project subtree.

### 1. Install on the target machine

```sh
brew install pipx          # macOS; one-time
pipx ensurepath            # one-time
pipx install git+https://github.com/dmitriibeliakov/todoist-cli.git
```

### 2. Save the token

```sh
echo "<TODOIST_TOKEN>" | todoist auth login
```

Token is written to `~/.config/todoist-cli/config.toml` with mode `0600`.

### 3. Set the scope

```sh
todoist scope set <PROJECT_ID_OR_PATH>
todoist scope show          # verify: <id>\t<path>
```

Use the project **id** (not name) when scripting — names can collide.

### 4. Lock the scope

Edit `~/.config/todoist-cli/config.toml` and add `locked = true` under `[scope]`:

```toml
token = "..."

[scope]
project_id = "6gc9gjR3PMHj3jvj"
locked = true
```

After this, `todoist scope set` and `todoist scope clear` will refuse with exit 3 until the operator manually edits the file. Verify:

```sh
todoist scope show          # expected: <id>\t<path>\tlocked
todoist scope clear         # expected: error: scope is locked ...
```

### 5. Wire `todoist-mcp` into the agent host

Point the agent's MCP config at the `todoist-mcp` binary on the target machine.

For Claude Code / Claude Desktop:

```jsonc
{
  "mcpServers": {
    "todoist": {
      "command": "todoist-mcp"
    }
  }
}
```

The agent should see exactly these tools: `list_tasks`, `get_task`, `add_task`, `complete_task`, `delete_task`, `postpone_task`, `set_task_priority`, `comment_on_task`, `list_projects`, `add_project`, `show_scope`. There is no `scope_set` / `scope_clear` tool by design — scope is operator-controlled.

### 6. Confirm fail-closed behavior

`todoist-mcp` refuses to start (exit 3) when no scope is configured. Test it on the target machine:

```sh
TODOIST_TOKEN=fake todoist-mcp                          # with no [scope] in config
# error: refusing to start MCP server without a scope lock.
```

Override only when you genuinely want full-account access on a trusted host:

```sh
TODOIST_MCP_ALLOW_UNSCOPED=1 todoist-mcp
```

---

## Personal use (full account)

For your own laptop where you want unrestricted access:

```sh
pipx install -e /path/to/repo
echo "<TOKEN>" | todoist auth login
# (skip scope; CLI defaults to full account)
todoist ls
```

Don't run `todoist-mcp` here unless you also set `TODOIST_MCP_ALLOW_UNSCOPED=1` — the MCP server fails closed on purpose.

---

## Updating

```sh
pipx upgrade todoist-cli
```

Re-running `auth login` preserves the `[scope]` section and `locked` flag.

---

## Threat model — what this does and doesn't protect against

The Todoist personal API token has **full account access**. There is no way to scope the token itself. The scope lock here is a CLI/MCP-side guardrail that stops a friendly agent that uses only these binaries from wandering outside its lane.

It does **not** protect against:

- Code that reads the token from `~/.config/todoist-cli/config.toml` and calls the Todoist REST API directly.
- A different MCP server (e.g. third-party `todoist-mcp` packages) installed alongside this one — those have no scope concept.
- Anyone with shell access to the target machine.

If you need real isolation, use a separate Todoist account whose token only sees that project.
