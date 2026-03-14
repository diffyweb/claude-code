---
description: "Install a Claude Code plugin directly from a GitHub repo (owner/repo or full URL)"
argument-hint: "owner/repo or GitHub URL"
---

# /quick-install — One-Command Plugin Installation

Install a Claude Code plugin from a GitHub repository without manually managing marketplaces.

## Input

`$ARGUMENTS` is either:
- `owner/repo` format (e.g., `Diffyweb/claude-plugin-quick-install`)
- A full GitHub URL (e.g., `https://github.com/Diffyweb/claude-plugin-quick-install` or `https://github.com/Diffyweb/claude-plugin-quick-install.git`)

## Steps

### 1. Parse the input

Extract `owner/repo` from the arguments. If a full URL is given, strip the `https://github.com/` prefix and any `.git` suffix.

### 2. Fetch plugin names from the marketplace manifest

```bash
curl -sL "https://raw.githubusercontent.com/$OWNER_REPO/main/.claude-plugin/marketplace.json" | python3 -c "import sys,json; [print(p['name']) for p in json.load(sys.stdin)['plugins']]"
```

If this fails, try `HEAD` or `master` as the branch instead of `main`.

If all fail (no `.claude-plugin/marketplace.json` in the repo), tell the user:
> "This repo doesn't have a `.claude-plugin/marketplace.json` manifest. It needs one to be installable as a Claude Code plugin. See https://code.claude.com/docs/en/plugin-marketplaces for the required format."

Stop here if it fails.

### 3. Derive the marketplace name

The marketplace name is `owner-repo` with the `/` replaced by `-`. For example:
- `Diffyweb/claude-plugin-quick-install` → `diffyweb-claude-plugin-quick-install`

### 4. Add the marketplace

```bash
claude plugin marketplace add "$OWNER_REPO"
```

If this fails, check if the marketplace already exists (run `claude plugin marketplace list` and look for the derived name). If it already exists, continue to step 5.

### 5. Install the plugin(s)

For each plugin name found in step 2:

```bash
claude plugin install "$PLUGIN_NAME@$MARKETPLACE_NAME"
```

If there's only one plugin (the common case), install it directly. If there are multiple, ask the user which ones they want, or install all if they say so.

### 6. Reload

Tell the user to run `/reload-plugins` to activate the new plugin in the current session.

## Output

Report what happened:
- Plugin name(s) installed
- Marketplace added (or already existed)
- Remind to run `/reload-plugins`

## Examples

```
/quick-install Diffyweb/claude-plugin-quick-install
/quick-install https://github.com/anthropics/claude-code
/quick-install EveryInc/compound-engineering-plugin
```
