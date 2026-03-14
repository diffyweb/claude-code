---
name: search-sessions
description: "List, summarize, or search past Claude Code sessions"
arguments:
  - name: action
    description: "list, summarize, search, or reindex"
    required: true
  - name: target
    description: "project fragment, session ID, or search query (depends on action)"
    required: false
---

# /search-sessions — Session History Tool

Route the user's request to the appropriate `sessions.py` subcommand.

## Routing

Based on the `$ARGUMENTS.action`:

### `list`

List recent sessions. If `$ARGUMENTS.target` is provided, use it as a project filter.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py list --project "$ARGUMENTS.target" --limit 20
```

Without a target:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py list --limit 20
```

### `summarize`

Summarize a specific session. `$ARGUMENTS.target` should be a session ID, file path, or `latest[:FRAGMENT]`.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py summarize "$ARGUMENTS.target" --include-tools
```

If no target is given, default to `latest`:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py summarize latest --include-tools
```

### `search`

Search conversation content. `$ARGUMENTS.target` is the search query.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py search "$ARGUMENTS.target" --limit 20
```

### `reindex`

Rebuild the BM25 search index. `$ARGUMENTS.target` is an optional project filter.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py reindex --project "$ARGUMENTS.target"
```

Without a target:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py reindex
```

## Output

All commands return JSON. Format the results for readability:
- **list**: Table with slug, project, date, first prompt
- **summarize**: Stats header, then conversation flow with key quotes
- **search**: Grouped by session with context snippets and BM25 scores

Offer follow-up actions (e.g., "Want me to summarize session X?" after a search).
