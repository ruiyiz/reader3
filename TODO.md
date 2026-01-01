# TODO - reader3

## PDF Support

### Current Status (2026-01-01)

✅ **Implemented:**
- Basic PDF processing via PyMuPDF (fitz)
- TOC/bookmark extraction when available
- Fallback to page-based chunking (10 pages per chapter) when no TOC exists
- Metadata extraction (title, author, publisher, date)
- Web upload interface for both EPUB and PDF files
- Command-line processing: `uv run reader3.py file.pdf`
- Unified reading experience with EPUB files

### Known Limitations

❌ **Does not work well with:**
- Scientific papers with complex formatting
- Multi-column layouts
- Papers with equations, figures, and tables
- PDFs with complex text positioning
- Image-heavy documents

**Root cause:** PyMuPDF's `get_text()` extracts text in reading order but loses:
- Formatting and structure
- Column layout information
- Proper ordering of text blocks in complex layouts
- Relationship between text, figures, and captions

### Future Improvements

#### High Priority
- [ ] **Better text extraction for scientific papers**
  - Consider using `page.get_text("blocks")` or `page.get_text("dict")` to preserve layout
  - Detect and handle multi-column layouts
  - Preserve reading order in complex documents

- [ ] **Enhanced formatting preservation**
  - Extract and convert formatting to HTML (bold, italic, headings)
  - Use PyMuPDF's text blocks to recreate document structure
  - Detect and mark section headings vs body text

- [ ] **Figure and table handling**
  - Extract images from PDF pages (PyMuPDF supports this)
  - Preserve image positions relative to text
  - Extract and format tables properly
  - Link captions to their figures/tables

#### Medium Priority
- [ ] **Mathematical equation support**
  - Detect equations in PDFs
  - Consider MathML or LaTeX extraction if available
  - Render equations properly in the web interface

- [ ] **Improved TOC handling**
  - Build hierarchical/nested TOC structure (currently flat)
  - Handle PDFs with missing or incomplete TOCs
  - Auto-generate TOC from section headings when TOC is missing

- [ ] **Better chunking strategies**
  - Smart chunking based on content (sections/headings) rather than page count
  - Configurable chunk size for different use cases
  - Preserve section boundaries

#### Low Priority
- [ ] **Annotation support**
  - Extract PDF annotations and highlights
  - Display them in the reader interface

- [ ] **OCR for scanned PDFs**
  - Detect scanned/image-based PDFs
  - Integrate OCR (e.g., Tesseract) for text extraction

- [ ] **PDF metadata enhancements**
  - Extract more metadata fields
  - Handle custom metadata properties

### Technical Notes

**PyMuPDF alternatives to explore:**
- `page.get_text("blocks")` - Returns text blocks with position info
- `page.get_text("dict")` - Returns detailed structure including fonts, sizes, positions
- `page.get_text("html")` - Exports as HTML (may preserve some formatting)
- `page.get_text("xhtml")` - XHTML export with better structure

**Potential libraries for better PDF processing:**
- `pdfplumber` - Better table and layout detection
- `pypdf` - Alternative PDF parser
- `camelot-py` - Specialized for table extraction
- `tabula-py` - Another table extraction library

**Research papers on PDF parsing:**
- Consider layout analysis algorithms
- Look into academic paper parsing tools (e.g., GROBID, Science Parse)

### Resources
- PyMuPDF docs: https://pymupdf.readthedocs.io/
- Issue tracking: Consider which improvements are most valuable for LLM-assisted reading

---

**Last Updated:** 2026-01-01
**Status:** PDF feature works for text-heavy documents; complex formatting support deferred
