from __future__ import annotations


def match_known(summary: str, known_texts: list[str], *, keywords: list[str] | None = None) -> str | None:
    blob = summary
    for text in known_texts:
        if text and text in blob:
            return text
    for word in keywords or []:
        if word and word in blob:
            return word
    return None
