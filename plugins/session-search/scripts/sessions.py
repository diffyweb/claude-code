#!/usr/bin/env python3
"""Search, list, and summarize past Claude Code sessions.

Usage:
    python3 sessions.py list [--project FRAGMENT] [--limit 20]
    python3 sessions.py summarize <target> [--max-turns 100] [--include-thinking] [--include-tools]
    python3 sessions.py search <query> [--project FRAGMENT] [--limit 20] [--context-chars 100] [--no-index]
    python3 sessions.py reindex [--project FRAGMENT]
"""

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------

def get_claude_base():
    """Return the expanded path to ~/.claude."""
    return Path.home() / ".claude"


def encode_project_path(path):
    """Encode a filesystem path the way Claude Code does for project dirs.

    Replaces every non-alphanumeric character with '-'.
    """
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def resolve_project_dirs(fragment=None):
    """Return project directories matching an optional substring fragment.

    With no fragment, returns all project directories.
    Fragment is matched case-insensitively against the encoded directory name.
    """
    projects_root = get_claude_base() / "projects"
    if not projects_root.is_dir():
        return []

    dirs = []
    fragment_lower = fragment.lower() if fragment else None
    for entry in sorted(projects_root.iterdir()):
        if not entry.is_dir():
            continue
        if fragment_lower and fragment_lower not in entry.name.lower():
            continue
        dirs.append(entry)
    return dirs


def get_session_files(project_dirs):
    """Yield (project_dir, session_file) tuples for all .jsonl files."""
    for pdir in project_dirs:
        for f in sorted(pdir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            yield pdir, f


def iter_session_lines(filepath, types=None):
    """Streaming generator over parsed JSONL lines.

    Args:
        filepath: Path to the .jsonl file.
        types: Optional set of type strings to include (e.g. {'user', 'assistant'}).
               If None, yields all successfully parsed lines.

    Yields:
        Parsed JSON objects, skipping malformed lines.
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if types and obj.get("type") not in types:
                continue
            yield obj


def extract_text(message, include_thinking=False):
    """Extract readable text from a message's content field.

    Handles both string content and array content.
    Skips thinking blocks and tool_result blocks by default.
    """
    content = message.get("content", "")
    if isinstance(content, str):
        return content

    parts = []
    for block in content:
        btype = block.get("type", "")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "thinking" and include_thinking:
            thinking = block.get("thinking", "")
            if thinking:
                parts.append(f"[thinking] {thinking}")
    return "\n".join(parts)


def extract_tool_uses(message):
    """Extract tool use names from an assistant message's content."""
    content = message.get("content", [])
    if isinstance(content, str):
        return []
    tools = []
    for block in content:
        if block.get("type") == "tool_use":
            tools.append(block.get("name", "unknown"))
    return tools


def get_session_metadata(filepath):
    """Quick-scan a session file for key metadata.

    Reads only enough lines to get: session_id, slug, branch, cwd, timestamps,
    and the first user prompt.
    """
    meta = {
        "session_id": None,
        "slug": None,
        "project": filepath.parent.name,
        "branch": None,
        "cwd": None,
        "first_timestamp": None,
        "last_timestamp": None,
        "first_prompt": None,
        "file_path": str(filepath),
    }

    # Quick scan: read first user message and capture metadata from early lines
    found_user = False
    for obj in iter_session_lines(filepath):
        if meta["session_id"] is None and obj.get("sessionId"):
            meta["session_id"] = obj["sessionId"]
        if meta["slug"] is None and obj.get("slug"):
            meta["slug"] = obj["slug"]
        if meta["branch"] is None and obj.get("gitBranch"):
            meta["branch"] = obj["gitBranch"]
        if meta["cwd"] is None and obj.get("cwd"):
            meta["cwd"] = obj["cwd"]
        if meta["first_timestamp"] is None and obj.get("timestamp"):
            meta["first_timestamp"] = obj["timestamp"]

        # Capture last timestamp from every line
        if obj.get("timestamp"):
            meta["last_timestamp"] = obj["timestamp"]

        if not found_user and obj.get("type") == "user":
            msg = obj.get("message", {})
            text = extract_text(msg)
            if text.strip():
                meta["first_prompt"] = text.strip()[:200]
                found_user = True

        # Once we have user prompt + slug, we can stop early for 'list'
        # But we still need last_timestamp, so we'll read on for slug
        if found_user and meta["slug"]:
            break

    # Always do a tail scan for last_timestamp (and slug if missing)
    try:
        with open(filepath, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 10240))
            tail = f.read().decode("utf-8", errors="replace")
            for line in reversed(tail.strip().split("\n")):
                try:
                    obj = json.loads(line)
                    if meta["slug"] is None and obj.get("slug"):
                        meta["slug"] = obj["slug"]
                    if obj.get("timestamp"):
                        if meta["last_timestamp"] is None or obj["timestamp"] > meta["last_timestamp"]:
                            meta["last_timestamp"] = obj["timestamp"]
                    if meta["slug"] and meta["last_timestamp"]:
                        break
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        pass

    return meta


def find_session_file(target):
    """Resolve a target to a session file path.

    Target can be:
    - A file path (absolute or relative)
    - A session ID (UUID)
    - 'latest' or 'latest:FRAGMENT' for most recent session
    """
    # Direct file path
    if os.path.isfile(target):
        return Path(target)

    # latest or latest:FRAGMENT
    if target.startswith("latest"):
        fragment = None
        if ":" in target:
            fragment = target.split(":", 1)[1]
        dirs = resolve_project_dirs(fragment)
        if not dirs:
            return None
        # Find most recently modified .jsonl across matching dirs
        newest = None
        newest_mtime = 0
        for pdir in dirs:
            for f in pdir.glob("*.jsonl"):
                mtime = f.stat().st_mtime
                if mtime > newest_mtime:
                    newest = f
                    newest_mtime = mtime
        return newest

    # Session ID — search all project dirs
    for pdir in resolve_project_dirs():
        candidate = pdir / f"{target}.jsonl"
        if candidate.is_file():
            return candidate
        # Also check if the target is a prefix
        for f in pdir.glob(f"{target}*.jsonl"):
            return f

    return None


# ---------------------------------------------------------------------------
# BM25 tokenizer
# ---------------------------------------------------------------------------

STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "had", "has", "have", "he", "her", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "just", "me", "my", "no", "not", "of", "on", "or",
    "our", "out", "so", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "to", "up", "us", "was", "we", "were",
    "what", "when", "which", "who", "will", "with", "would", "you", "your",
})

# Simple suffix rules: (suffix, min_word_len, replacement)
_SUFFIX_RULES = [
    ("ying", 5, "y"),
    ("ies", 4, "y"),
    ("ness", 5, ""),
    ("ment", 5, ""),
    ("tion", 5, ""),
    ("sion", 5, ""),
    ("ings", 5, ""),
    ("ing", 4, ""),
    ("able", 5, ""),
    ("ible", 5, ""),
    ("ally", 5, ""),
    ("ful", 4, ""),
    ("ous", 4, ""),
    ("ive", 4, ""),
    ("ers", 4, ""),
    ("ed", 3, ""),
    ("er", 3, ""),
    ("ly", 3, ""),
    ("es", 3, ""),
    ("s", 3, ""),
]


def _stem(word):
    """Simple suffix stemmer — not Porter, but covers common English cases."""
    for suffix, min_len, replacement in _SUFFIX_RULES:
        if len(word) >= min_len and word.endswith(suffix):
            return word[:-len(suffix)] + replacement
    return word


def tokenize(text):
    """Tokenize text: lowercase, split on non-alphanumeric, filter stops, stem."""
    words = re.split(r"[^a-z0-9]+", text.lower())
    return [_stem(w) for w in words if w and w not in STOPWORDS and len(w) > 1]


# ---------------------------------------------------------------------------
# BM25 index management
# ---------------------------------------------------------------------------

INDEX_VERSION = 1
INDEX_PATH = get_claude_base() / "session-search-index.json"


def _empty_index():
    return {
        "version": INDEX_VERSION,
        "doc_count": 0,
        "avg_doc_len": 0.0,
        "files": {},      # {path_str: mtime_float}
        "terms": {},      # {term: {"df": int, "postings": [{"id": doc_id, "tf": int}]}}
        "docs": {},       # {doc_id: {"len": int, "project": str, "slug": str, "path": str, "first_timestamp": str, "first_prompt": str}}
    }


def load_index():
    """Load the BM25 index from disk. Returns empty index on any error."""
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            idx = json.load(f)
        if idx.get("version") != INDEX_VERSION:
            return _empty_index()
        return idx
    except (OSError, json.JSONDecodeError, ValueError, KeyError):
        return _empty_index()


def save_index(idx):
    """Write the BM25 index to disk."""
    try:
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(idx, f, separators=(",", ":"))
    except OSError as e:
        print(json.dumps({"warning": f"Failed to save index: {e}"}), file=sys.stderr)


def _extract_session_text(filepath):
    """Extract all user and assistant text from a session for indexing."""
    parts = []
    for obj in iter_session_lines(filepath, types={"user", "assistant"}):
        msg = obj.get("message", {})
        text = extract_text(msg)
        if text and text.strip():
            parts.append(text.strip())
    return "\n".join(parts)


def _add_doc_to_index(idx, doc_id, tokens, meta):
    """Add a document's tokens to the index."""
    doc_len = len(tokens)
    idx["docs"][doc_id] = {
        "len": doc_len,
        "project": meta.get("project", ""),
        "slug": meta.get("slug", ""),
        "path": meta.get("file_path", ""),
        "first_timestamp": meta.get("first_timestamp", ""),
        "first_prompt": meta.get("first_prompt", ""),
    }

    # Count term frequencies
    tf_map = {}
    for token in tokens:
        tf_map[token] = tf_map.get(token, 0) + 1

    # Update term postings
    for term, tf in tf_map.items():
        if term not in idx["terms"]:
            idx["terms"][term] = {"df": 0, "postings": []}
        entry = idx["terms"][term]
        entry["df"] += 1
        entry["postings"].append({"id": doc_id, "tf": tf})


def _remove_doc_from_index(idx, doc_id):
    """Remove a document from the index."""
    if doc_id not in idx["docs"]:
        return

    del idx["docs"][doc_id]

    # Clean up term postings
    stale_terms = []
    for term, entry in idx["terms"].items():
        entry["postings"] = [p for p in entry["postings"] if p["id"] != doc_id]
        if entry["postings"]:
            entry["df"] = len(entry["postings"])
        else:
            stale_terms.append(term)

    for term in stale_terms:
        del idx["terms"][term]


def build_or_update_index(project_fragment=None):
    """Build or incrementally update the BM25 index.

    Scans session files, compares mtime, indexes new/modified files,
    prunes stale entries.
    """
    idx = load_index()
    dirs = resolve_project_dirs(project_fragment)

    # Collect current session files
    current_files = {}
    for pdir, sfile in get_session_files(dirs):
        path_str = str(sfile)
        current_files[path_str] = sfile.stat().st_mtime

    # Prune stale entries (files that no longer exist or aren't in scope)
    stale_paths = [p for p in idx["files"] if p not in current_files]
    for path_str in stale_paths:
        # Find doc_id for this path
        doc_id_to_remove = None
        for doc_id, doc in idx["docs"].items():
            if doc.get("path") == path_str:
                doc_id_to_remove = doc_id
                break
        if doc_id_to_remove:
            _remove_doc_from_index(idx, doc_id_to_remove)
        del idx["files"][path_str]

    # Index new or modified files
    indexed_count = 0
    for path_str, mtime in current_files.items():
        old_mtime = idx["files"].get(path_str)
        if old_mtime is not None and mtime <= old_mtime:
            continue  # Unchanged

        filepath = Path(path_str)

        # Remove old version if re-indexing
        if old_mtime is not None:
            for doc_id, doc in list(idx["docs"].items()):
                if doc.get("path") == path_str:
                    _remove_doc_from_index(idx, doc_id)
                    break

        # Index the session
        meta = get_session_metadata(filepath)
        doc_id = meta.get("session_id") or filepath.stem
        text = _extract_session_text(filepath)
        tokens = tokenize(text)

        if tokens:
            _add_doc_to_index(idx, doc_id, tokens, meta)

        idx["files"][path_str] = mtime
        indexed_count += 1

    # Recompute aggregate stats
    idx["doc_count"] = len(idx["docs"])
    total_len = sum(d["len"] for d in idx["docs"].values())
    idx["avg_doc_len"] = total_len / idx["doc_count"] if idx["doc_count"] > 0 else 0.0

    save_index(idx)
    return idx, indexed_count


# ---------------------------------------------------------------------------
# BM25 scoring
# ---------------------------------------------------------------------------

def bm25_search(idx, query_text, limit=20):
    """Score documents against a query using BM25.

    Returns [(doc_id, score)] sorted by score descending.
    """
    query_tokens = tokenize(query_text)
    if not query_tokens:
        return []

    N = idx["doc_count"]
    if N == 0:
        return []

    avg_dl = idx["avg_doc_len"]
    k1 = 1.5
    b = 0.75

    scores = {}

    for token in query_tokens:
        term_entry = idx["terms"].get(token)
        if not term_entry:
            continue

        df = term_entry["df"]
        idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)

        for posting in term_entry["postings"]:
            doc_id = posting["id"]
            tf = posting["tf"]
            doc_len = idx["docs"][doc_id]["len"]

            tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_dl))
            score = idf * tf_norm

            scores[doc_id] = scores.get(doc_id, 0.0) + score

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked[:limit]


# ---------------------------------------------------------------------------
# list subcommand
# ---------------------------------------------------------------------------

def cmd_list(args):
    """List recent sessions, optionally filtered by project."""
    dirs = resolve_project_dirs(args.project)
    if not dirs:
        print(json.dumps({"sessions": [], "total": 0, "showing": 0,
                          "error": f"No project directories found matching '{args.project}'" if args.project else "No project directories found"}))
        return

    sessions = []
    for pdir, sfile in get_session_files(dirs):
        meta = get_session_metadata(sfile)
        sessions.append(meta)

    # Sort by first_timestamp descending (newest first)
    sessions.sort(key=lambda s: s.get("first_timestamp") or "", reverse=True)

    total = len(sessions)
    showing = sessions[:args.limit]

    result = {
        "sessions": showing,
        "total": total,
        "showing": len(showing),
    }
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# summarize subcommand
# ---------------------------------------------------------------------------

def cmd_summarize(args):
    """Summarize a single session."""
    filepath = find_session_file(args.target)
    if filepath is None:
        print(json.dumps({"error": f"Session not found: {args.target}"}))
        return

    meta = get_session_metadata(filepath)
    max_turns = args.max_turns
    include_thinking = args.include_thinking
    include_tools = args.include_tools

    conversation = []
    tool_counts = {}
    user_count = 0
    assistant_count = 0
    total_tool_uses = 0

    # Track which assistant message IDs we've already seen text for
    seen_assistant_ids = set()

    for obj in iter_session_lines(filepath, types={"user", "assistant"}):
        msg = obj.get("message", {})
        role = msg.get("role")
        timestamp = obj.get("timestamp")
        msg_id = msg.get("id")

        if role == "user":
            text = extract_text(msg)
            # Skip tool_result-only messages (no human-readable text)
            if not text.strip():
                continue
            user_count += 1
            conversation.append({
                "turn": len(conversation) + 1,
                "role": "user",
                "timestamp": timestamp,
                "text": text.strip(),
            })

        elif role == "assistant":
            text = extract_text(msg, include_thinking=include_thinking)
            tools = extract_tool_uses(msg)

            # Track tool usage
            for tool in tools:
                tool_counts[tool] = tool_counts.get(tool, 0) + 1
                total_tool_uses += 1

            # Deduplicate: assistant messages stream as multiple JSONL lines
            # with the same msg_id. Accumulate text, count tools once per line.
            if msg_id and msg_id in seen_assistant_ids:
                # Append text to the last assistant entry if it has more content
                if text.strip() and conversation and conversation[-1]["role"] == "assistant":
                    existing = conversation[-1]["text"]
                    if text.strip() not in existing:
                        conversation[-1]["text"] = (existing + "\n" + text.strip()).strip()
                    if include_tools and tools:
                        prev_tools = conversation[-1].get("tools_used", [])
                        conversation[-1]["tools_used"] = prev_tools + tools
                continue

            if msg_id:
                seen_assistant_ids.add(msg_id)

            if not text.strip() and not tools:
                continue

            assistant_count += 1
            entry = {
                "turn": len(conversation) + 1,
                "role": "assistant",
                "timestamp": timestamp,
                "text": text.strip()[:500] if text.strip() else "",
            }
            if include_tools and tools:
                entry["tools_used"] = tools
            conversation.append(entry)

    # Apply max_turns truncation
    truncated = False
    if len(conversation) > max_turns:
        truncated = True
        half = max_turns // 2
        first = conversation[:half]
        last = conversation[-half:]
        omitted = len(conversation) - max_turns
        conversation = first + [{
            "turn": "...",
            "role": "system",
            "text": f"[{omitted} turns omitted]",
        }] + last
        # Renumber turns in the last half
        for i, entry in enumerate(conversation[half + 1:], start=half + 2):
            if isinstance(entry.get("turn"), int):
                entry["turn"] = i

    result = {
        "session_id": meta["session_id"],
        "slug": meta["slug"],
        "project": meta["project"],
        "branch": meta["branch"],
        "cwd": meta["cwd"],
        "time_range": {
            "start": meta["first_timestamp"],
            "end": meta["last_timestamp"],
        },
        "stats": {
            "user_messages": user_count,
            "assistant_messages": assistant_count,
            "tool_uses": total_tool_uses,
            "tool_breakdown": tool_counts,
        },
        "conversation_flow": conversation,
        "truncated": truncated,
    }
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# search subcommand
# ---------------------------------------------------------------------------

def _substring_search(args):
    """Original substring search — used as fallback when BM25 is unavailable."""
    query = args.query.lower()
    dirs = resolve_project_dirs(args.project)
    if not dirs:
        return {"query": args.query, "results": [], "total_results": 0,
                "sessions_searched": 0, "search_method": "substring",
                "error": f"No project directories found matching '{args.project}'" if args.project else "No project directories found"}

    results = []
    sessions_searched = 0
    context_chars = args.context_chars

    for pdir, sfile in get_session_files(dirs):
        sessions_searched += 1
        session_matches = []
        session_meta = None

        with open(sfile, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                # Raw-string pre-filter: skip lines that can't contain the query
                if query not in line.lower():
                    continue

                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                if obj.get("type") not in ("user", "assistant"):
                    continue

                msg = obj.get("message", {})
                role = msg.get("role")
                text = extract_text(msg)
                if not text:
                    continue

                text_lower = text.lower()
                if query not in text_lower:
                    continue

                # Capture metadata from first matching line
                if session_meta is None:
                    session_meta = {
                        "session_id": obj.get("sessionId"),
                        "slug": obj.get("slug"),
                        "project": pdir.name,
                        "date": obj.get("timestamp"),
                    }

                # Extract snippet with context
                idx = text_lower.index(query)
                start = max(0, idx - context_chars)
                end = min(len(text), idx + len(query) + context_chars)
                snippet = text[start:end]
                if start > 0:
                    snippet = "..." + snippet
                if end < len(text):
                    snippet = snippet + "..."

                session_matches.append({
                    "role": role,
                    "timestamp": obj.get("timestamp"),
                    "snippet": snippet,
                })

        if session_matches and session_meta:
            results.append({
                **session_meta,
                "matches": session_matches[:10],
                "match_count": len(session_matches),
            })

        if len(results) >= args.limit:
            break

    # Sort by date descending
    results.sort(key=lambda r: r.get("date") or "", reverse=True)

    return {
        "query": args.query,
        "results": results[:args.limit],
        "total_results": sum(r["match_count"] for r in results),
        "sessions_searched": sessions_searched,
        "search_method": "substring",
    }


def _bm25_search(args):
    """BM25 ranked search with snippet extraction from matching files."""
    # Build or update index
    idx, indexed_count = build_or_update_index(args.project)

    if idx["doc_count"] == 0:
        return {"query": args.query, "results": [], "total_results": 0,
                "sessions_searched": 0, "search_method": "bm25",
                "index_docs": 0}

    # Run BM25 scoring
    ranked = bm25_search(idx, args.query, limit=args.limit)
    if not ranked:
        return {"query": args.query, "results": [], "total_results": 0,
                "sessions_searched": idx["doc_count"], "search_method": "bm25",
                "index_docs": idx["doc_count"]}

    # For each ranked result, load snippets from the session file
    results = []
    context_chars = args.context_chars
    query_lower = args.query.lower()

    for doc_id, score in ranked:
        doc = idx["docs"].get(doc_id)
        if not doc:
            continue

        filepath = Path(doc["path"])
        if not filepath.is_file():
            continue

        # Extract snippets via substring scan of the matched file
        session_matches = []
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if query_lower not in line.lower():
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if obj.get("type") not in ("user", "assistant"):
                    continue
                msg = obj.get("message", {})
                text = extract_text(msg)
                if not text:
                    continue
                text_lower = text.lower()
                if query_lower not in text_lower:
                    continue

                pos = text_lower.index(query_lower)
                start = max(0, pos - context_chars)
                end = min(len(text), pos + len(args.query) + context_chars)
                snippet = text[start:end]
                if start > 0:
                    snippet = "..." + snippet
                if end < len(text):
                    snippet = snippet + "..."

                session_matches.append({
                    "role": msg.get("role"),
                    "timestamp": obj.get("timestamp"),
                    "snippet": snippet,
                })

                if len(session_matches) >= 10:
                    break

        results.append({
            "session_id": doc_id,
            "slug": doc.get("slug"),
            "project": doc.get("project"),
            "date": doc.get("first_timestamp"),
            "first_prompt": doc.get("first_prompt"),
            "bm25_score": round(score, 3),
            "matches": session_matches,
            "match_count": len(session_matches),
        })

    return {
        "query": args.query,
        "results": results,
        "total_results": sum(r["match_count"] for r in results),
        "sessions_searched": idx["doc_count"],
        "search_method": "bm25",
        "index_docs": idx["doc_count"],
    }


def cmd_search(args):
    """Search conversation content across sessions."""
    use_substring = getattr(args, "no_index", False)

    if use_substring:
        output = _substring_search(args)
    else:
        try:
            output = _bm25_search(args)
        except Exception:
            # BM25 failed — fall back to substring
            output = _substring_search(args)
            output["search_method"] = "substring (bm25 fallback)"

    print(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# reindex subcommand
# ---------------------------------------------------------------------------

def cmd_reindex(args):
    """Rebuild the BM25 search index from scratch."""
    # Delete existing index
    try:
        INDEX_PATH.unlink(missing_ok=True)
    except OSError:
        pass

    idx, indexed_count = build_or_update_index(args.project)

    result = {
        "status": "ok",
        "indexed_sessions": indexed_count,
        "total_docs": idx["doc_count"],
        "total_terms": len(idx["terms"]),
        "index_path": str(INDEX_PATH),
    }
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Search, list, and summarize past Claude Code sessions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser("list", help="List recent sessions")
    p_list.add_argument("--project", "-p", default=None,
                        help="Filter by project name fragment")
    p_list.add_argument("--limit", "-l", type=int, default=20,
                        help="Max sessions to return (default: 20)")
    p_list.set_defaults(func=cmd_list)

    # summarize
    p_sum = subparsers.add_parser("summarize", help="Summarize a session")
    p_sum.add_argument("target",
                       help="Session ID, file path, or 'latest[:FRAGMENT]'")
    p_sum.add_argument("--max-turns", type=int, default=100,
                       help="Max conversation turns to include (default: 100)")
    p_sum.add_argument("--include-thinking", action="store_true",
                       help="Include thinking blocks in output")
    p_sum.add_argument("--include-tools", action="store_true",
                       help="Include tool use names in conversation flow")
    p_sum.set_defaults(func=cmd_summarize)

    # search
    p_search = subparsers.add_parser("search", help="Search conversation content")
    p_search.add_argument("query", help="Search string")
    p_search.add_argument("--project", "-p", default=None,
                          help="Filter by project name fragment")
    p_search.add_argument("--limit", "-l", type=int, default=20,
                          help="Max sessions to return (default: 20)")
    p_search.add_argument("--context-chars", "-c", type=int, default=100,
                          help="Characters of context around matches (default: 100)")
    p_search.add_argument("--no-index", action="store_true",
                          help="Force substring search instead of BM25")
    p_search.set_defaults(func=cmd_search)

    # reindex
    p_reindex = subparsers.add_parser("reindex", help="Rebuild the BM25 search index")
    p_reindex.add_argument("--project", "-p", default=None,
                           help="Only reindex sessions matching this project fragment")
    p_reindex.set_defaults(func=cmd_reindex)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
