"""md 解析：frontmatter、wikilink、标题层级切节。"""

from __future__ import annotations

import re

import frontmatter

from ragdb.ingest.schema import ParsedNote, RawDocument, Section

_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_WIKILINK = re.compile(r"\[\[([^\]\|#]+)")


def _normalize_tags(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    return [str(t).strip() for t in raw if str(t).strip()]


def parse_note(doc: RawDocument) -> ParsedNote:
    post = frontmatter.loads(doc.content)
    meta: dict = dict(post.metadata)
    tags = _normalize_tags(meta.get("tags"))

    wikilinks: list[str] = []
    seen: set[str] = set()
    for m in _WIKILINK.finditer(post.content):
        link = m.group(1).strip()
        if link and link not in seen:
            seen.add(link)
            wikilinks.append(link)

    lines = post.content.splitlines()
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    buf: list[str] = []
    preamble = True

    def flush(level: int) -> None:
        text = "\n".join(buf).strip()
        if not text and (level == 0 and not stack and not sections):
            return
        if not text:
            return
        if level == 0:
            path = doc.title
        else:
            path = " > ".join([doc.title, *(t for _, t in stack)])
        sections.append(Section(heading_path=path, content=text, level=level))

    for line in lines:
        m = _HEADING.match(line)
        if m:
            flush(0 if preamble else stack[-1][0])
            buf = []
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
            preamble = False
        else:
            buf.append(line)

    if preamble and not stack:
        flush(0)
    else:
        flush(stack[-1][0] if stack else 0)

    return ParsedNote(
        doc=doc, frontmatter=meta, wikilinks=wikilinks, tags=tags, sections=sections
    )
