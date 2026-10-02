"""Compile source templates and transparent format-specificity heuristics."""

import math
import re

SEPARATORS = " -·•./|"
TOKEN = re.compile(r"\[[^]]+\]|\\u[0-9a-fA-F]{4}|\\.|[^\\]")


def template_pattern(template: str, alphabet: str) -> str:
    result = []
    for char in template:
        if alphabet == "a-n":
            atom = {"a": "[A-Z]", "n": "[0-9]"}.get(char, re.escape(char))
        elif "A" <= char <= "Z":
            atom = "[A-Z0-9]" if char == "X" else "[A-Z]"
        elif char.isdecimal():
            atom = "[0-9]"
        else:
            atom = re.escape(char)
        result.append(atom)
    return "".join(result)


def relaxed_pattern(pattern: str) -> str:
    """Only declared punctuation positions may disappear or change separators."""
    # Never edit inside an alphanumeric character class or a capture name.
    result = []
    for token in TOKEN.findall(pattern):
        body = token[1:-1] if token.startswith("[") else token.removeprefix("\\")
        if token not in ("|", ".") and body and all(c in SEPARATORS for c in body):
            result.append("[ .·•/|\\-]*")
        else:
            result.append(token)
    # Optional punctuation atoms have already become zero-or-more.
    return "".join(result).replace("*?", "*")


def specificity(pattern: str) -> float:
    """Information in required slots against a 36-character baseline; heuristic."""
    pattern = re.sub(r"\(\?P<[^>]+>", "(", pattern).replace("(?:", "(")
    branches = pattern.split("|")
    totals = []
    for branch in branches:
        total = 0.0
        tokens = list(TOKEN.finditer(branch))
        skip_to = 0
        for token in tokens:
            if token.start() < skip_to:
                continue
            atom = token[0]
            suffix = branch[token.end() :]
            repeat = re.match(r"\{([0-9]+)(?:,[0-9]*)?\}|[?*+]", suffix)
            count = 1
            if repeat:
                count = int(repeat[1]) if repeat[1] else (0 if repeat[0] in "?*" else 1)
                skip_to = token.end() + repeat.end()
            if atom.startswith("["):
                body = atom[1:-1]
                body = re.sub(
                    r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), body
                )
                size = 0
                i = 0
                while i < len(body):
                    if i + 2 < len(body) and body[i + 1] == "-":
                        size += max(0, ord(body[i + 2]) - ord(body[i]) + 1)
                        i += 3
                    else:
                        size += 1
                        i += 1
                if body and not all(c in SEPARATORS for c in body):
                    total += count * max(0, math.log2(36 / max(1, size)))
            elif atom.isalnum() or atom.startswith("\\u"):
                total += count * math.log2(36)
        totals.append(total)
    return round(min(totals, default=0.0), 6)
