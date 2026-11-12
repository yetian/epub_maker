# AGENTS.md

Project guide for coding agents working in this repository.

## Overview

`txt2epub.py` is a single-file command-line tool that converts Chinese TXT
novels into EPUB. It has three stages: encoding detection, chapter splitting,
and EPUB generation via EbookLib.

## Environment

- Python 3.10+
- Dependencies: `EbookLib`, `charset-normalizer`, `chardet`

Install dependencies:

```bash
pip install EbookLib charset-normalizer chardet
```

## Common commands

```bash
# Syntax check
python3 -m py_compile txt2epub.py

# Run on the sample file (writes EPUB next to input)
python3 txt2epub.py example.txt --no-interactive

# Force an encoding
python3 txt2epub.py input.txt -e gb18030

# Inspect the generated EPUB
unzip -l output.epub
unzip -p output.epub EPUB/nav.xhtml
```

There is no test suite or linter configured. Verify changes by running the
script against a real TXT file and checking:
- the detected encoding,
- the number and titles of chapters,
- the generated `.epub` structure (`nav.xhtml`, `content.opf`, `chap_*.xhtml`).

## Code map

- `detect_encoding()` / `_score_decoded()` / `_prompt_encoding()`: encoding
  detection, scoring, and interactive fallback.
- `split_chapters()` / `_match_heading()`: chapter and preamble extraction.
- `build_epub()`: EPUB assembly, spine, and TOC.
- `main()`: CLI argument parsing.

## Conventions

- Keep the tool a single self-contained script unless a strong reason appears.
- Preserve the existing function/CLI names and behavior.
- Regexes for chapter headings live near the top of the chapter section; adjust
  them there rather than scattering patterns.
- Do not commit generated `.epub` files, `__pycache__`, or the sample novel.
- EPUB content must stay UTF-8; never write decoded text back to disk in a
  legacy encoding.
- Commit every change after finishing a task; do not leave modifications
  uncommitted.
