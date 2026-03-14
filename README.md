# Diffyweb Claude Code

Claude Code plugins and skills by [Diffyweb](https://github.com/diffyweb).

## Add This Marketplace

```
/plugin marketplace add diffyweb/claude-code
```

## Available Plugins

| Plugin | Description |
|--------|-------------|
| `quick-install` | Install Claude Code plugins from a GitHub repo in one command |
| `session-search` | Search, list, and summarize past Claude Code sessions with BM25 ranked retrieval |

## Install a Plugin

```
/plugin install quick-install@diffyweb-claude-code
/plugin install session-search@diffyweb-claude-code
```

## Structure

```
├── .claude-plugin/
│   └── marketplace.json        # Marketplace manifest
├── plugins/
│   ├── quick-install/           # /quick-install command
│   └── session-search/         # /search-sessions command + auto-triggered skill
└── skills/                      # (future standalone skills)
```
