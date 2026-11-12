#!/usr/bin/env python3
"""Convert a Chinese plain-text novel into an EPUB.

Features:
  * Automatic encoding detection (UTF-8 / GBK / Big5 / ...), with an
    interactive picker when the result is uncertain.
  * Chapter detection based on headings such as 第一章, 第1章, 1, and
    keyword headings such as 前言 / 楔子 / 序言 / 推荐 ...
  * Text before the first recognised heading becomes a chapter named "标题".
  * One paragraph per source line.
  * EPUB TOC generated from the detected chapters.
"""

import argparse
import html
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field

try:
    from charset_normalizer import from_bytes as _cn_from_bytes
except ImportError:  # pragma: no cover
    _cn_from_bytes = None

try:
    import chardet
except ImportError:  # pragma: no cover
    chardet = None

try:
    from ebooklib import epub
except ImportError:  # pragma: no cover
    epub = None


# ---------------------------------------------------------------------------
# Encoding detection
# ---------------------------------------------------------------------------

# Fixed candidates that are commonly found in Chinese TXT novels.  The order
# matters only when scores are equal.
_COMMON_ENCODINGS = [
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "gb18030",
    "gbk",
    "gb2312",
    "big5",
    "big5hkscs",
    "cp950",
]

_CJK_RANGES = (
    (0x3400, 0x4DBF),   # CJK Extension A
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0xF900, 0xFAFF),   # Compatibility Ideographs
    (0x20000, 0x2FA1F), # Extension B-F
)

_MOJIBAKE_MARKERS = (
    "Ã", "Â", "â€", "ï¿½", "å¤", "ã€", "ã‚", "ãƒ", "Ð", "Ñ",
    "µ", "¶", "·", "»", "¿",
)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _score_decoded(text: str) -> float:
    """Heuristic quality score for a decoded string. Higher is better."""
    if not text:
        return float("-inf")

    sample = text[:200_000]
    total = len(sample)
    cjk = 0
    bad = 0
    for ch in sample:
        if _is_cjk(ch):
            cjk += 1
        elif ch in "\r\n\t" or ch == "\u3000":
            continue
        else:
            cat = unicodedata.category(ch)
            if cat == "Cc" or ch == "\ufffd":
                bad += 1

    score = (cjk / total) * 100.0
    score -= (bad / total) * 200.0

    for marker in _MOJIBAKE_MARKERS:
        score -= sample.count(marker) * 0.5

    return score


@dataclass
class Candidate:
    encoding: str
    score: float
    sample: str


def _try_decode(data: bytes, encoding: str):
    try:
        return data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return None


def detect_encoding(data: bytes, interactive: bool = True):
    """Return (text, encoding).

    If detection is uncertain and ``interactive`` is True the user is asked
    to pick a candidate.  Otherwise the best guess is returned.
    """
    # BOM based decisions are unambiguous.
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig"
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16"), "utf-16"

    # Strict UTF-8 is a very strong signal.
    utf8_text = _try_decode(data, "utf-8")
    if utf8_text is not None:
        return utf8_text, "utf-8"

    candidates: dict[str, Candidate] = {}

    # charset_normalizer gives a strong hint for legacy CJK encodings.
    cn_best_encoding = None
    cn_best_chaos = None
    if _cn_from_bytes is not None:
        try:
            result = _cn_from_bytes(data)
            for guess in list(result)[:5]:
                enc = guess.encoding
                if not enc:
                    continue
                text = _try_decode(data, enc)
                if text is None:
                    continue
                candidates[enc] = Candidate(enc, _score_decoded(text), text)
            best = result.best()
            if best is not None and best.encoding:
                cn_best_encoding = best.encoding
                cn_best_chaos = best.percent_chaos
        except Exception:
            pass

    # chardet as a second opinion.
    if chardet is not None:
        try:
            guess = chardet.detect(data[:200_000])
            enc = guess.get("encoding")
            if enc:
                text = _try_decode(data, enc)
                if text is not None:
                    candidates.setdefault(
                        enc, Candidate(enc, _score_decoded(text), text)
                    )
        except Exception:
            pass

    # Always try the common Chinese encodings explicitly.
    for enc in _COMMON_ENCODINGS:
        if enc in candidates:
            continue
        text = _try_decode(data, enc)
        if text is not None:
            candidates[enc] = Candidate(enc, _score_decoded(text), text)

    if not candidates:
        # Last resort: decode with replacement so the user can still see text.
        text = data.decode("utf-8", errors="replace")
        return text, "utf-8"

    ranked = sorted(candidates.values(), key=lambda c: c.score, reverse=True)
    best = ranked[0]

    # Confidence rules.
    confident = False
    if cn_best_encoding and best.encoding == cn_best_encoding and cn_best_chaos is not None:
        if cn_best_chaos < 0.10:
            confident = True
    if len(ranked) == 1:
        confident = True
    if len(ranked) > 1 and best.score - ranked[1].score >= 15:
        confident = True

    if confident or not interactive:
        return best.sample, best.encoding

    return _prompt_encoding(data, ranked)


def _prompt_encoding(data: bytes, ranked: list[Candidate]):
    print("\nEncoding detection is uncertain. Candidates:")
    for idx, cand in enumerate(ranked, 1):
        preview = cand.sample[:60].replace("\r", " ").replace("\n", " ")
        print(f"  [{idx}] {cand.encoding:<12} score={cand.score:6.2f}  {preview}")
    print("  [m] enter an encoding name manually")

    while True:
        choice = input("Choose encoding [1]: ").strip() or "1"
        if choice.lower() == "m":
            enc = input("Encoding name: ").strip()
            text = _try_decode(data, enc)
            if text is None:
                print(f"Cannot decode as {enc!r}. Try again.")
                continue
            return text, enc
        if choice.isdigit() and 1 <= int(choice) <= len(ranked):
            cand = ranked[int(choice) - 1]
            return cand.sample, cand.encoding
        print("Invalid choice.")


# ---------------------------------------------------------------------------
# Chapter detection
# ---------------------------------------------------------------------------

_CN_DIGITS = "零〇一二三四五六七八九十百千万两廿卅0123456789０１２３４５６７８９"

# 第一章 / 第1章 / 第一百二十三回 / 第 12 节 ...
_RE_CHAPTER = re.compile(
    rf"^\s*第\s*[{_CN_DIGITS}]+\s*[章回节集卷部篇](.*)$"
)

# Bare number: "1" / "12." / "（3）" / "1、标题" ...
_RE_NUMBER = re.compile(
    r"^\s*[（(]?\s*[0-9０-９]+\s*[)）]?\s*(?:[.．、:：]\s*(.*))?$"
)

# Keyword headings: 前言 / 楔子 / 序言 / 推荐 / 后记 ...
_RE_KEYWORD = re.compile(
    r"^\s*(内容简介|简介|前言|序言|序章|序|楔子|引子|推荐语|推荐序|推荐|"
    r"后记|尾声|番外篇|番外|感言|上架感言|作者的话|正文)\s*[:：]?\s*(.*)$"
)

# Keywords that must be the entire line (avoid matching body text).
_STRICT_KEYWORDS = {
    "内容简介", "简介", "前言", "序言", "序章", "序", "楔子", "引子",
    "推荐语", "推荐序", "推荐", "后记", "尾声", "番外篇", "番外",
    "感言", "上架感言", "作者的话", "正文",
}

_SENTENCE_END = "。！？…!?；;，,、：:」』”\"'）)】]"


@dataclass
class Heading:
    line_index: int
    title: str
    bare: bool  # True if the heading is just "第X章" with no title text


def _match_heading(line: str):
    stripped = line.strip()
    if not stripped or len(stripped) > 60:
        return None

    m = _RE_CHAPTER.match(stripped)
    if m:
        rest = (m.group(1) or "").strip(" \t:：.-—　")
        return Heading(-1, stripped, rest == "")

    m = _RE_KEYWORD.match(stripped)
    if m:
        keyword, rest = m.group(1), (m.group(2) or "").strip(" \t:：.-—　")
        # For most keywords require the line to be short (title-like).
        if keyword in _STRICT_KEYWORDS and len(stripped) > 30:
            return None
        return Heading(-1, stripped, rest == "")

    m = _RE_NUMBER.match(stripped)
    if m:
        # Only accept bare numbers on their own line, or short numbered titles.
        rest = (m.group(1) or "").strip()
        if not rest:
            return Heading(-1, stripped, True)
        if len(rest) <= 30:
            return Heading(-1, stripped, False)

    return None


def _looks_like_title_continuation(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 40:
        return False
    if _match_heading(s) is not None:
        return False
    if s[-1] in _SENTENCE_END:
        return False
    return True


def split_chapters(text: str):
    """Split raw text into a list of (title, [paragraph lines])."""
    lines = text.splitlines()

    headings: list[Heading] = []
    for i, line in enumerate(lines):
        h = _match_heading(line)
        if h is not None:
            h.line_index = i
            headings.append(h)

    chapters: list[tuple[str, list[str]]] = []

    # Text before the first heading.
    first_idx = headings[0].line_index if headings else len(lines)
    preamble = lines[:first_idx]
    if any(l.strip() for l in preamble):
        chapters.append(("标题", preamble))

    if not headings:
        return chapters if chapters else [("正文", lines)]

    for k, h in enumerate(headings):
        start = h.line_index
        end = headings[k + 1].line_index if k + 1 < len(headings) else len(lines)

        title = h.title
        content_start = start + 1

        # If the heading is bare ("第一章"), pull the following short line in
        # as the chapter name.
        if h.bare and content_start < end:
            nxt = lines[content_start]
            if _looks_like_title_continuation(nxt):
                title = f"{title} {nxt.strip()}".strip()
                content_start += 1

        content = lines[content_start:end]
        chapters.append((title, content))

    return chapters


# ---------------------------------------------------------------------------
# EPUB generation
# ---------------------------------------------------------------------------

_CSS = """\
body { font-family: serif; line-height: 1.6; }
h1, h2 { text-align: center; margin: 1em 0; }
p { text-indent: 2em; margin: 0.4em 0; }
"""


def _paragraph_html(line: str) -> str | None:
    text = line.strip()
    if not text:
        return None
    return f"<p>{html.escape(text)}</p>"


def build_epub(chapters, output_path: str, book_title: str, author: str = "Unknown"):
    if epub is None:
        raise RuntimeError("ebooklib is not installed. Run: pip install EbookLib")

    book = epub.EpubBook()
    book.set_identifier(f"txt2epub-{abs(hash((book_title, output_path))):x}")
    book.set_title(book_title)
    book.set_language("zh")
    book.add_author(author)

    style = epub.EpubItem(
        uid="style",
        file_name="style/main.css",
        media_type="text/css",
        content=_CSS,
    )
    book.add_item(style)

    spine = ["nav"]
    toc = []

    for idx, (title, lines) in enumerate(chapters, 1):
        paragraphs = [p for p in (_paragraph_html(l) for l in lines) if p]
        body = "\n".join(paragraphs) or "<p></p>"
        item = epub.EpubHtml(
            title=title,
            file_name=f"chap_{idx:04d}.xhtml",
            lang="zh",
        )
        item.content = f"<h2>{html.escape(title)}</h2>\n{body}"
        item.add_item(style)
        book.add_item(item)
        spine.append(item)
        toc.append(epub.Link(item.file_name, title, f"chap_{idx:04d}"))

    book.toc = tuple(toc)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    epub.write_epub(output_path, book)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert a Chinese TXT novel into EPUB."
    )
    parser.add_argument("input", help="input .txt file")
    parser.add_argument("-o", "--output", help="output .epub path")
    parser.add_argument(
        "-e", "--encoding",
        help="force input encoding (skips detection)",
    )
    parser.add_argument("--author", default="Unknown", help="author name")
    parser.add_argument("--title", help="book title (default: from filename)")
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="never prompt; use best guess when uncertain",
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.input):
        parser.error(f"input file not found: {args.input}")

    with open(args.input, "rb") as fh:
        data = fh.read()

    if args.encoding:
        try:
            text = data.decode(args.encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            parser.error(f"cannot decode with {args.encoding!r}: {exc}")
        encoding = args.encoding
    else:
        text, encoding = detect_encoding(data, interactive=not args.no_interactive)

    print(f"Detected encoding: {encoding}")

    chapters = split_chapters(text)
    if not chapters:
        parser.error("no content found")

    book_title = args.title or os.path.splitext(os.path.basename(args.input))[0]
    output = args.output or os.path.splitext(args.input)[0] + ".epub"

    build_epub(chapters, output, book_title, author=args.author)

    print(f"Chapters: {len(chapters)}")
    for title, lines in chapters[:5]:
        print(f"  - {title} ({len([l for l in lines if l.strip()])} paragraphs)")
    if len(chapters) > 5:
        print(f"  ... ({len(chapters) - 5} more)")
    print(f"EPUB written: {output}")


if __name__ == "__main__":
    main()
