---
name: session-search
description: >
  Search, list, and summarize past Claude Code sessions.
  Use when the user says: "session search", "past session", "find session",
  "what did we discuss", "previous conversation", "session history",
  "find conversation", "yesterday's session", "search sessions",
  "what did we decide", "in the last session", "we discussed",
  "look up that conversation", "check past sessions",
  "search my conversations", "find in conversations",
  "conversation history", "search history", "recent sessions".
---

# Session Search

## When to Use

Activate this skill when:
- The user asks about a past session, conversation, or decision ("what did we decide about X?")
- The user wants to search across session history ("find sessions about auth")
- You need context from another project's session history
- The user references a previous conversation ("in the last session...", "we discussed...")
- You need to find where something was implemented or discussed
- The user asks to list, search, or summarize sessions

## Commands

All commands use `${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py`. Output is always JSON — format it for the user.

### List Sessions

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py list [--project FRAGMENT] [--limit 20]
```

- `--project` filters by substring match against the encoded project path (e.g., `wp-term-icon`, `bookmark`)
- Returns: session IDs, slugs, project names, dates, first prompts
- Sorted by date descending

### Summarize a Session

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py summarize <target> [--max-turns 100] [--include-thinking] [--include-tools]
```

Target can be:
- A session UUID: `58edf39b-a1cc-4e6c-a3d1-e263321dbdc0`
- A file path: `~/.claude/projects/-Users-mc-project/session.jsonl`
- `latest` — most recent session across all projects
- `latest:FRAGMENT` — most recent session matching project fragment (e.g., `latest:wp-term-icon`)

Returns: session metadata, message stats, tool usage breakdown, and conversation flow with user prompts (full) and assistant responses (truncated to 500 chars).

Options:
- `--max-turns 100` — cap output. Long sessions get first-50 + last-50 with omission marker.
- `--include-thinking` — include thinking blocks (large, usually not useful)
- `--include-tools` — show tool names in conversation flow entries

### Search Across Sessions

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py search <query> [--project FRAGMENT] [--limit 20] [--context-chars 100] [--no-index]
```

- Uses BM25 ranked retrieval by default — results are scored by relevance
- Falls back to substring search if the index is unavailable or `--no-index` is passed
- Output includes `search_method` ("bm25" or "substring") and `bm25_score` per result
- `--context-chars` controls snippet length around matches

### Rebuild Index

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py reindex [--project FRAGMENT]
```

- Deletes and rebuilds the BM25 index from scratch
- Use when search results seem stale or after bulk session changes

## Re-ranking Guidance

When presenting BM25 search results to the user:

1. **Review the top results** — BM25 scores indicate term-frequency relevance but not semantic relevance. A session about "auth tokens" may score high for "token" even if the user meant "design tokens."
2. **Filter false positives** — If a result's snippets clearly don't match the user's intent, exclude it from your response.
3. **Summarize best matches** — For the top 2-3 genuinely relevant results, offer a brief description of what was discussed and offer to summarize the full session.
4. **Suggest refinements** — If results are noisy, suggest narrowing with `--project` or rephrasing the query.

## Workflow Patterns

### Find-then-summarize (most common)

1. Search for what the user is looking for:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py search "auth architecture" --project my-app
   ```
2. Summarize the most relevant session:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py summarize <session_id> --include-tools
   ```

### Latest session for a project

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py summarize latest:wp-term-icon
```

### Browse recent sessions

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py list --limit 10
```

## Formatting Guidance

- When presenting **list** results: show as a table with slug, project, date, and first prompt (truncated)
- When presenting **summarize** results: lead with stats, then the conversation flow. Quote key user prompts and assistant decisions.
- When presenting **search** results: group by session, show snippets with context, include BM25 score for transparency. Link to session IDs for deeper inspection.
- Always offer to summarize a session if search results look promising.

## Edge Cases

- **No slug**: Short or aborted sessions may not have a slug. Use session ID instead.
- **Empty first_prompt**: Some sessions start with tool_result lines (resumed sessions). The first_prompt may be a system message — note this when displaying.
- **Large sessions**: Sessions with 500+ turns will be truncated by `--max-turns`. The output includes a `truncated: true` flag.
- **Missing project**: If `--project` matches nothing, the output includes an error message. Suggest the user check available project names with `list`.
- **Index corruption**: If the BM25 index is corrupt, search automatically falls back to substring matching. Run `reindex` to rebuild.

## JSONL Format Reference

For manual parsing or edge cases not covered by the script, see `${CLAUDE_PLUGIN_ROOT}/references/jsonl-schema.md`.

Key points:
- Sessions stored in `~/.claude/projects/<encoded-path>/<session-uuid>.jsonl`
- Path encoding: replace non-alphanumeric chars with `-`
- Line types: `user`, `assistant`, `progress`, `file-history-snapshot`
- Assistant messages may span multiple JSONL lines (same `message.id`)
- Content blocks: `text`, `thinking`, `tool_use` (assistant) or `tool_result` (user)
