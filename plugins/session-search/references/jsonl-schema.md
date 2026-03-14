# Claude Code JSONL Session Format

Sessions are stored as JSONL files in `~/.claude/projects/<encoded-path>/`.

The encoded path replaces every non-alphanumeric character with `-`.
Example: `/Users/mc/Atrium/Code/my-project` → `-Users-mc-Atrium-Code-my-project`

Each session file is named `<session-uuid>.jsonl`.

## Common Fields (all line types)

```json
{
  "parentUuid": "uuid|null",
  "isSidechain": false,
  "userType": "external",
  "cwd": "/absolute/path",
  "sessionId": "uuid",
  "version": "2.1.72",
  "gitBranch": "main",
  "slug": "adjective-adjective-noun",
  "type": "user|assistant|progress|file-history-snapshot",
  "uuid": "uuid",
  "timestamp": "2026-03-11T10:52:36.971Z"
}
```

- `slug` appears after the session gets one (may be absent from early lines)
- `parentUuid` links lines into a conversation tree
- `isSidechain` marks branched/retried responses

## Line Types

### `user`

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": "string or array"
  },
  "permissionMode": "default"
}
```

Content is a **string** for human messages, or an **array** for tool results:

```json
{
  "content": [
    {
      "tool_use_id": "toolu_xxx",
      "type": "tool_result",
      "content": "The file was written successfully."
    }
  ]
}
```

### `assistant`

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-opus-4-6",
    "id": "msg_xxx",
    "role": "assistant",
    "content": [],
    "stop_reason": "end_turn|tool_use|null",
    "usage": {}
  },
  "requestId": "req_xxx"
}
```

Content array blocks:

| type | key fields | notes |
|------|-----------|-------|
| `text` | `text` | Readable assistant output |
| `thinking` | `thinking`, `signature` | Internal reasoning (large, often empty string) |
| `tool_use` | `id`, `name`, `input` | Tool invocation — `input` is a dict |

**Streaming note**: A single logical assistant response may span multiple JSONL lines with the same `message.id`. Each line contains incremental content blocks. To reconstruct the full response, collect all blocks with the same `message.id`.

### `progress`

```json
{
  "type": "progress",
  "data": {
    "type": "hook_progress|api_progress",
    "hookEvent": "SessionStart|PostToolUse|...",
    "hookName": "PostToolUse:Edit",
    "command": "bash script.sh"
  },
  "parentToolUseID": "toolu_xxx",
  "toolUseID": "toolu_xxx"
}
```

### `file-history-snapshot`

```json
{
  "type": "file-history-snapshot",
  "messageId": "uuid",
  "snapshot": {
    "messageId": "uuid",
    "trackedFileBackups": {},
    "timestamp": "iso8601"
  },
  "isSnapshotUpdate": false
}
```

## Manual Parsing Recipes

### Get first user prompt from a session
```bash
python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    for line in f:
        obj = json.loads(line)
        if obj.get('type') == 'user':
            content = obj['message'].get('content', '')
            if isinstance(content, str) and content.strip():
                print(content[:500]); break
" /path/to/session.jsonl
```

### Count tool uses by name
```bash
python3 -c "
import json, sys, collections
counts = collections.Counter()
with open(sys.argv[1]) as f:
    for line in f:
        try:
            obj = json.loads(line)
            if obj.get('type') == 'assistant':
                for block in obj.get('message',{}).get('content',[]):
                    if block.get('type') == 'tool_use':
                        counts[block['name']] += 1
        except: pass
for name, count in counts.most_common():
    print(f'{count:4d}  {name}')
" /path/to/session.jsonl
```

### Extract all assistant text (no thinking, no tools)
```bash
python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    for line in f:
        try:
            obj = json.loads(line)
            if obj.get('type') == 'assistant':
                for block in obj.get('message',{}).get('content',[]):
                    if block.get('type') == 'text' and block.get('text','').strip():
                        print(block['text'])
        except: pass
" /path/to/session.jsonl
```
