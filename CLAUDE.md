# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

reader3 is a lightweight, self-hosted EPUB reader designed for reading books alongside LLMs. It processes EPUB files into a local library and serves them via a web interface, making it easy to copy chapter content to LLMs for AI-assisted reading.

**Philosophy**: This is intentionally minimal demonstration code. Avoid adding complexity, abstractions, or features beyond what's explicitly requested. Code simplicity over extensibility.

## Commands

### Process an EPUB file
```bash
uv run reader3.py <epub-file>
```
Creates a `<bookname>_data/` folder containing `book.pkl` and extracted images.

### Run the web server
```bash
uv run server.py
```
Starts the FastAPI server at `http://127.0.0.1:8123`

### Package management
This project uses `uv` (not pip/virtualenv). Dependencies are in `pyproject.toml`.

## Architecture

### Two-part system
1. **reader3.py** - EPUB processor (run once per book)
2. **server.py** - Web server (serves all processed books)

### Data flow
```
EPUB file → reader3.py → book_data/ folder → server.py → web interface
                         ├── book.pkl (serialized Book object)
                         └── images/ (extracted images)
```

### Core data model (reader3.py:17-67)

- **Book** - Master object (pickled to disk)
  - `metadata: BookMetadata` - Title, authors, etc.
  - `spine: List[ChapterContent]` - Linear reading order (physical files)
  - `toc: List[TOCEntry]` - Navigation tree (logical structure)
  - `images: Dict[str, str]` - Image path mappings

- **ChapterContent** - Represents a physical file in EPUB spine
  - Contains cleaned HTML and plain text for LLM usage
  - `order` field preserves linear reading sequence

- **TOCEntry** - Hierarchical navigation structure
  - Maps to spine items via `file_href`
  - Supports nested children (recursive)

### Spine vs TOC

**Critical distinction**: The EPUB spine (linear reading order) is the source of truth for chapter sequence. The TOC is decorative/navigational but secondary. Navigation works by:
1. TOC entries reference spine items via `file_href`
2. JavaScript in reader.html maps TOC clicks to spine indices
3. Prev/Next navigation uses spine order

### Processing pipeline (reader3.py:175-283)

1. Load EPUB with ebooklib
2. Extract metadata
3. Extract and save images locally (images/ folder)
4. Parse TOC structure (recursive, handles nested sections)
5. Process spine content in linear order:
   - Clean HTML (remove scripts, styles, forms, iframes)
   - Rewrite image paths to local references
   - Extract plain text for LLM usage
   - Extract only body content
6. Pickle Book object

### Server architecture (server.py)

- **File-based library**: Auto-discovers `*_data` folders in current directory
- **LRU cache**: Books loaded into memory (max 10) to avoid repeated disk I/O
- **No database**: Library state = filesystem state
- **Static URLs**: Chapter indices map directly to spine positions

### Web templates

- **library.html** - Grid view of all processed books
- **reader.html** - Two-column layout:
  - Left sidebar: Recursive TOC with active state highlighting
  - Right content: Current chapter with prev/next navigation
  - JavaScript handles TOC→spine index mapping

## Key implementation details

### Image handling
- Images extracted to `<book>_data/images/`
- Paths rewritten in HTML to relative references
- Server.py serves images via `/read/{book_id}/images/{image_name}`
- Image map uses both full path and basename as keys for robustness

### HTML sanitization
Aggressive cleanup for security and simplicity:
- Removes: scripts, styles, iframes, videos, forms, buttons, nav
- Extracts only body content
- Plain text extraction for LLM/search usage

### TOC parsing
Handles three ebooklib types recursively:
- `tuple` (Section with children)
- `epub.Link` (leaf entries)
- `epub.Section` (standalone sections)
- Fallback: If TOC empty, generates flat TOC from spine

### Security
- Path sanitization with `os.path.basename()` prevents directory traversal
- HTML cleaning removes executable content
- Local-only server binding (127.0.0.1)

## Limitations by design

- No multi-user support
- No reading progress tracking
- No bookmarks or annotations
- No search functionality
- Single-threaded server suitable for personal use
- Author states project is "not supported"
