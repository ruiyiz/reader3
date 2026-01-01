"""
Parses an EPUB file into a structured object that can be used to serve the book via a web interface.
"""

import os
import pickle
import shutil
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime
from urllib.parse import unquote

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, Comment
import fitz  # PyMuPDF

# --- Data structures ---

@dataclass
class ChapterContent:
    """
    Represents a physical file in the EPUB (Spine Item).
    A single file might contain multiple logical chapters (TOC entries).
    """
    id: str           # Internal ID (e.g., 'item_1')
    href: str         # Filename (e.g., 'part01.html')
    title: str        # Best guess title from file
    content: str      # Cleaned HTML with rewritten image paths
    text: str         # Plain text for search/LLM context
    order: int        # Linear reading order


@dataclass
class TOCEntry:
    """Represents a logical entry in the navigation sidebar."""
    title: str
    href: str         # original href (e.g., 'part01.html#chapter1')
    file_href: str    # just the filename (e.g., 'part01.html')
    anchor: str       # just the anchor (e.g., 'chapter1'), empty if none
    children: List['TOCEntry'] = field(default_factory=list)


@dataclass
class BookMetadata:
    """Metadata"""
    title: str
    language: str
    authors: List[str] = field(default_factory=list)
    description: Optional[str] = None
    publisher: Optional[str] = None
    date: Optional[str] = None
    identifiers: List[str] = field(default_factory=list)
    subjects: List[str] = field(default_factory=list)


@dataclass
class Book:
    """The Master Object to be pickled."""
    metadata: BookMetadata
    spine: List[ChapterContent]  # The actual content (linear files)
    toc: List[TOCEntry]          # The navigation tree
    images: Dict[str, str]       # Map: original_path -> local_path

    # Meta info
    source_file: str
    processed_at: str
    version: str = "3.0"


# --- Utilities ---

def clean_html_content(soup: BeautifulSoup) -> BeautifulSoup:

    # Remove dangerous/useless tags
    for tag in soup(['script', 'style', 'iframe', 'video', 'nav', 'form', 'button']):
        tag.decompose()

    # Remove HTML comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove input tags
    for tag in soup.find_all('input'):
        tag.decompose()

    return soup


def extract_plain_text(soup: BeautifulSoup) -> str:
    """Extract clean text for LLM/Search usage."""
    text = soup.get_text(separator=' ')
    # Collapse whitespace
    return ' '.join(text.split())


def parse_toc_recursive(toc_list, depth=0) -> List[TOCEntry]:
    """
    Recursively parses the TOC structure from ebooklib.
    """
    result = []

    for item in toc_list:
        # ebooklib TOC items are either `Link` objects or tuples (Section, [Children])
        if isinstance(item, tuple):
            section, children = item
            entry = TOCEntry(
                title=section.title,
                href=section.href,
                file_href=section.href.split('#')[0],
                anchor=section.href.split('#')[1] if '#' in section.href else "",
                children=parse_toc_recursive(children, depth + 1)
            )
            result.append(entry)
        elif isinstance(item, epub.Link):
            entry = TOCEntry(
                title=item.title,
                href=item.href,
                file_href=item.href.split('#')[0],
                anchor=item.href.split('#')[1] if '#' in item.href else ""
            )
            result.append(entry)
        # Note: ebooklib sometimes returns direct Section objects without children
        elif isinstance(item, epub.Section):
             entry = TOCEntry(
                title=item.title,
                href=item.href,
                file_href=item.href.split('#')[0],
                anchor=item.href.split('#')[1] if '#' in item.href else ""
            )
             result.append(entry)

    return result


def get_fallback_toc(book_obj) -> List[TOCEntry]:
    """
    If TOC is missing, build a flat one from the Spine.
    """
    toc = []
    for item in book_obj.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            name = item.get_name()
            # Try to guess a title from the content or ID
            title = item.get_name().replace('.html', '').replace('.xhtml', '').replace('_', ' ').title()
            toc.append(TOCEntry(title=title, href=name, file_href=name, anchor=""))
    return toc


def extract_metadata_robust(book_obj) -> BookMetadata:
    """
    Extracts metadata handling both single and list values.
    """
    def get_list(key):
        data = book_obj.get_metadata('DC', key)
        return [x[0] for x in data] if data else []

    def get_one(key):
        data = book_obj.get_metadata('DC', key)
        return data[0][0] if data else None

    return BookMetadata(
        title=get_one('title') or "Untitled",
        language=get_one('language') or "en",
        authors=get_list('creator'),
        description=get_one('description'),
        publisher=get_one('publisher'),
        date=get_one('date'),
        identifiers=get_list('identifier'),
        subjects=get_list('subject')
    )


# --- Main Conversion Logic ---

def split_chapter_by_anchors(chapter_content: str, toc_entries: List[TOCEntry], soup: BeautifulSoup) -> List[tuple]:
    """
    Splits a chapter's HTML content into multiple sections based on TOC anchor positions.
    Returns list of (anchor_id, title, html_content, text_content) tuples.
    """
    if not toc_entries:
        return []

    # Find anchor elements and their positions
    anchor_positions = []
    all_elements = list(soup.descendants)

    for toc_entry in toc_entries:
        if toc_entry.anchor:
            # Find element with this ID
            anchor_elem = soup.find(id=toc_entry.anchor)
            if anchor_elem:
                try:
                    pos = all_elements.index(anchor_elem)
                    anchor_positions.append((pos, anchor_elem, toc_entry))
                except ValueError:
                    pass

    if not anchor_positions:
        return []

    # Sort by position in document
    anchor_positions.sort(key=lambda x: x[0])

    # Get body content as a single string
    body = soup.find('body')
    if not body:
        body = soup

    body_html = str(body)

    # Split content by finding anchor markers in the HTML
    sections = []

    for idx, (pos, anchor_elem, toc_entry) in enumerate(anchor_positions):
        anchor_id = toc_entry.anchor

        # Find where this anchor appears in the HTML
        anchor_marker = f'id="{anchor_id}"'
        start_pos = body_html.find(anchor_marker)

        if start_pos == -1:
            # Try with single quotes
            anchor_marker = f"id='{anchor_id}'"
            start_pos = body_html.find(anchor_marker)

        if start_pos == -1:
            continue

        # Find the start of this section (back up to the opening tag)
        tag_start = body_html.rfind('<', 0, start_pos)

        # Find where the next section starts (or end of content)
        if idx + 1 < len(anchor_positions):
            next_anchor_id = anchor_positions[idx + 1][2].anchor
            next_marker = f'id="{next_anchor_id}"'
            end_pos = body_html.find(next_marker)
            if end_pos == -1:
                next_marker = f"id='{next_anchor_id}'"
                end_pos = body_html.find(next_marker)
            if end_pos != -1:
                end_pos = body_html.rfind('<', 0, end_pos)
            else:
                end_pos = len(body_html)
        else:
            # Last section - take everything until end
            end_pos = len(body_html)

        # Extract section HTML
        section_html = body_html[tag_start:end_pos]

        # Parse and extract text
        section_soup = BeautifulSoup(section_html, 'html.parser')
        section_text = extract_plain_text(section_soup)

        sections.append((anchor_id, toc_entry.title, section_html, section_text))

    return sections


def process_epub(epub_path: str, output_dir: str) -> Book:

    # 1. Load Book
    print(f"Loading {epub_path}...")
    book = epub.read_epub(epub_path)

    # 2. Extract Metadata
    metadata = extract_metadata_robust(book)

    # 3. Prepare Output Directories
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    images_dir = os.path.join(output_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)

    # 4. Extract Images & Build Map
    print("Extracting images...")
    image_map = {} # Key: internal_path, Value: local_relative_path

    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            # Normalize filename
            original_fname = os.path.basename(item.get_name())
            # Sanitize filename for OS
            safe_fname = "".join([c for c in original_fname if c.isalpha() or c.isdigit() or c in '._-']).strip()

            # Save to disk
            local_path = os.path.join(images_dir, safe_fname)
            with open(local_path, 'wb') as f:
                f.write(item.get_content())

            # Map keys: We try both the full internal path and just the basename
            # to be robust against messy HTML src attributes
            rel_path = f"images/{safe_fname}"
            image_map[item.get_name()] = rel_path
            image_map[original_fname] = rel_path

    # 5. Process TOC
    print("Parsing Table of Contents...")
    toc_structure = parse_toc_recursive(book.toc)
    if not toc_structure:
        print("Warning: Empty TOC, building fallback from Spine...")
        toc_structure = get_fallback_toc(book)

    # 5b. Build a flat list of all TOC entries for lookup
    def flatten_toc(toc_list: List[TOCEntry]) -> List[TOCEntry]:
        result = []
        for entry in toc_list:
            result.append(entry)
            if entry.children:
                result.extend(flatten_toc(entry.children))
        return result

    flat_toc = flatten_toc(toc_structure)

    # 6. Process Content (Spine-based to preserve HTML validity)
    print("Processing chapters...")
    spine_chapters = []

    # We iterate over the spine (linear reading order)
    for i, spine_item in enumerate(book.spine):
        item_id, linear = spine_item
        item = book.get_item_with_id(item_id)

        if not item:
            continue

        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            # Raw content
            raw_content = item.get_content().decode('utf-8', errors='ignore')
            soup = BeautifulSoup(raw_content, 'html.parser')

            # A. Fix Images
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if not src: continue

                # Decode URL (part01/image%201.jpg -> part01/image 1.jpg)
                src_decoded = unquote(src)
                filename = os.path.basename(src_decoded)

                # Try to find in map
                if src_decoded in image_map:
                    img['src'] = image_map[src_decoded]
                elif filename in image_map:
                    img['src'] = image_map[filename]

            # B. Clean HTML
            soup = clean_html_content(soup)

            # C. Check if this file has multiple TOC entries with anchors
            file_href = item.get_name()
            toc_entries = [t for t in flat_toc if t.file_href == file_href and t.anchor]

            if len(toc_entries) > 1:
                # Split this file into multiple chapters
                print(f"  Splitting {file_href} into {len(toc_entries)} sections...")
                sections = split_chapter_by_anchors(raw_content, toc_entries, soup)

                for section_idx, (anchor, title, section_html, section_text) in enumerate(sections):
                    chapter = ChapterContent(
                        id=f"{item_id}#{anchor}",
                        href=f"{file_href}#{anchor}",
                        title=title,
                        content=section_html,
                        text=section_text,
                        order=len(spine_chapters)
                    )
                    spine_chapters.append(chapter)
            else:
                # D. Extract Body Content only (single section)
                body = soup.find('body')
                if body:
                    # Extract inner HTML of body
                    final_html = "".join([str(x) for x in body.contents])
                else:
                    final_html = str(soup)

                # E. Create Object
                # Try to find a TOC entry for this file to get a better title
                matching_toc = next((t for t in flat_toc if t.file_href == file_href), None)
                title = matching_toc.title if matching_toc else f"Section {i+1}"

                chapter = ChapterContent(
                    id=item_id,
                    href=item.get_name(),
                    title=title,
                    content=final_html,
                    text=extract_plain_text(soup),
                    order=len(spine_chapters)
                )
                spine_chapters.append(chapter)

    # 7. Final Assembly
    final_book = Book(
        metadata=metadata,
        spine=spine_chapters,
        toc=toc_structure,
        images=image_map,
        source_file=os.path.basename(epub_path),
        processed_at=datetime.now().isoformat()
    )

    return final_book


def process_pdf(pdf_path: str, output_dir: str) -> Book:
    """
    Process a PDF file into a Book object.
    Attempts to extract TOC/bookmarks, falls back to page-based chunking if unavailable.
    """
    print(f"Loading {pdf_path}...")
    doc = fitz.open(pdf_path)

    # 1. Extract Metadata
    metadata_dict = doc.metadata
    title = metadata_dict.get('title', os.path.splitext(os.path.basename(pdf_path))[0])
    if not title or title.strip() == '':
        title = os.path.splitext(os.path.basename(pdf_path))[0]

    author = metadata_dict.get('author', 'Unknown')
    authors = [author] if author else []

    metadata = BookMetadata(
        title=title,
        language="en",
        authors=authors,
        description=metadata_dict.get('subject'),
        publisher=metadata_dict.get('producer'),
        date=metadata_dict.get('creationDate')
    )

    # 2. Prepare Output Directory
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    images_dir = os.path.join(output_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)

    # 3. Try to Extract TOC/Outline
    print("Extracting Table of Contents...")
    toc_outline = doc.get_toc(simple=False)

    spine_chapters = []
    toc_structure = []

    if toc_outline and len(toc_outline) > 0:
        # TOC exists - use it to create chapters
        print(f"Found {len(toc_outline)} TOC entries")

        # Build chapter ranges from TOC
        chapter_ranges = []
        for i, entry in enumerate(toc_outline):
            # TOC entries can have 3 or 4 elements: [level, title, page] or [level, title, page, dest]
            level, title, page_num = entry[0], entry[1], entry[2]
            start_page = page_num - 1  # fitz uses 0-based indexing

            # Find end page (start of next entry at same or higher level)
            end_page = len(doc) - 1
            for j in range(i + 1, len(toc_outline)):
                next_entry = toc_outline[j]
                next_level, next_page = next_entry[0], next_entry[2]
                if next_level <= level:
                    end_page = next_page - 2
                    break

            chapter_ranges.append({
                'level': level,
                'title': title,
                'start': start_page,
                'end': end_page,
                'order': i
            })

        # Create ChapterContent objects from TOC entries
        for i, chapter_info in enumerate(chapter_ranges):
            text_parts = []
            html_parts = ["<div>"]

            for page_num in range(chapter_info['start'], chapter_info['end'] + 1):
                if page_num < 0 or page_num >= len(doc):
                    continue
                page = doc[page_num]
                page_text = page.get_text()
                text_parts.append(page_text)
                html_parts.append(f"<p>{page_text.replace(chr(10), '<br>')}</p>")

            html_parts.append("</div>")

            chapter = ChapterContent(
                id=f"chapter_{i}",
                href=f"chapter_{i}.html",
                title=chapter_info['title'],
                content="".join(html_parts),
                text=" ".join(text_parts),
                order=i
            )
            spine_chapters.append(chapter)

            # Build TOC structure (flat for now - nested TOC would be more complex)
            toc_entry = TOCEntry(
                title=chapter_info['title'],
                href=f"chapter_{i}.html",
                file_href=f"chapter_{i}.html",
                anchor=""
            )
            toc_structure.append(toc_entry)

    else:
        # No TOC - fall back to page-based chunking
        print("No TOC found, using page-based chunking...")
        pages_per_chapter = 10
        total_pages = len(doc)

        for chunk_start in range(0, total_pages, pages_per_chapter):
            chunk_end = min(chunk_start + pages_per_chapter, total_pages)
            chapter_num = chunk_start // pages_per_chapter

            text_parts = []
            html_parts = ["<div>"]

            for page_num in range(chunk_start, chunk_end):
                page = doc[page_num]
                page_text = page.get_text()
                text_parts.append(page_text)
                html_parts.append(f"<p>{page_text.replace(chr(10), '<br>')}</p>")

            html_parts.append("</div>")

            title = f"Pages {chunk_start + 1}-{chunk_end}"
            chapter = ChapterContent(
                id=f"chapter_{chapter_num}",
                href=f"chapter_{chapter_num}.html",
                title=title,
                content="".join(html_parts),
                text=" ".join(text_parts),
                order=chapter_num
            )
            spine_chapters.append(chapter)

            toc_entry = TOCEntry(
                title=title,
                href=f"chapter_{chapter_num}.html",
                file_href=f"chapter_{chapter_num}.html",
                anchor=""
            )
            toc_structure.append(toc_entry)

    doc.close()

    # 4. Create Book object
    final_book = Book(
        metadata=metadata,
        spine=spine_chapters,
        toc=toc_structure,
        images={},  # PDF image extraction can be added later if needed
        source_file=os.path.basename(pdf_path),
        processed_at=datetime.now().isoformat()
    )

    return final_book


def save_to_pickle(book: Book, output_dir: str):
    p_path = os.path.join(output_dir, 'book.pkl')
    with open(p_path, 'wb') as f:
        pickle.dump(book, f)
    print(f"Saved structured data to {p_path}")


# --- CLI ---

if __name__ == "__main__":

    import sys
    if len(sys.argv) < 2:
        print("Usage: python reader3.py <file.epub|file.pdf>")
        sys.exit(1)

    input_file = sys.argv[1]
    assert os.path.exists(input_file), "File not found."

    # Detect file type
    file_ext = os.path.splitext(input_file)[1].lower()
    out_dir = os.path.splitext(input_file)[0] + "_data"

    # Process based on file type
    if file_ext == '.epub':
        book_obj = process_epub(input_file, out_dir)
    elif file_ext == '.pdf':
        book_obj = process_pdf(input_file, out_dir)
    else:
        print(f"Unsupported file type: {file_ext}")
        print("Supported formats: .epub, .pdf")
        sys.exit(1)

    save_to_pickle(book_obj, out_dir)
    print("\n--- Summary ---")
    print(f"Title: {book_obj.metadata.title}")
    print(f"Authors: {', '.join(book_obj.metadata.authors)}")
    print(f"Physical Files (Spine): {len(book_obj.spine)}")
    print(f"TOC Root Items: {len(book_obj.toc)}")
    print(f"Images extracted: {len(book_obj.images)}")
