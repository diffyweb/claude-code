# Diffyweb Claude Code

Claude Code plugins and skills by [Diffyweb](https://github.com/diffyweb).

## Skills

| Skill | Description |
|-------|-------------|
| `quick-install` | Install Claude Code plugins from a GitHub repo in one command |

## Plugins

| Plugin | Description |
|--------|-------------|
| `session-search` | Search, list, and summarize past Claude Code sessions with BM25 ranked retrieval |

## Structure

```
├── skills/
│   └── quick-install/           # /quick-install skill (standalone, ~/.claude/skills/)
├── plugins/
│   └── session-search/         # /search-sessions command + auto-triggered skill
```
