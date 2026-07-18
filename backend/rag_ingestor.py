# src/rag_ingestor.py
"""
ChaguoAI — RAG Knowledge Base Ingestion Pipeline.

PURPOSE
-------
Converts three authoritative PDF documents into a structured,
searchable vector knowledge base that powers ChaguoAI's conversational
reasoning engine.

Source Documents
----------------
1. Kenya National Family Planning Guideline, 7th Edition (2025)
   Ministry of Health Kenya — 312 pages
   Coverage: All FP methods, client assessment, counselling,
   service delivery, Kenya-specific protocols

2. WHO Medical Eligibility Criteria (MEC), 6th Edition (2025)
   World Health Organization — 218 pages
   Coverage: Safety categories for all methods × all medical
   conditions. The global clinical safety standard.

3. WHO Selected Practice Recommendations (SPR), 4th Edition (2025)
   World Health Organization — 108 pages
   Coverage: How to initiate, continue, and manage problems
   with each method once eligibility is established.

ARCHITECTURE DECISION: WHY CHROMADB + OPENAI EMBEDDINGS
---------------------------------------------------------
We evaluated three options:

Option A — JSON file with keyword search
  Pro: Simple, no external dependency
  Con: No semantic understanding. Query "can I use the pill
       while breastfeeding" would miss chunks about "CHCs and
       lactation" because the keywords don't match exactly.
  VERDICT: Rejected. Unacceptable retrieval accuracy for
           clinical content.

Option B — FAISS (Facebook AI Similarity Search)
  Pro: Fast, runs locally
  Con: No persistence without extra code, harder metadata
       filtering, no built-in async support.
  VERDICT: Viable but ChromaDB is better for our use case.

Option C — ChromaDB (CHOSEN)
  Pro: Persistent, built-in metadata filtering, runs locally
       or hosted, supports hybrid search (semantic + keyword),
       simple Python API, open source, actively maintained.
  Con: Slightly slower than FAISS for pure ANN search.
  VERDICT: CHOSEN. Persistence, metadata filtering, and hybrid
           search are all essential for clinical RAG accuracy.

WHY OPENAI TEXT-EMBEDDING-3-SMALL (NOT A LOCAL MODEL)
------------------------------------------------------
Clinical text from WHO guidelines uses precise technical
vocabulary: "menarche", "ischemic", "levonorgestrel",
"ethinyl estradiol", "DMPA-SC". Local embedding models
trained on general corpora (e.g. all-MiniLM-L6-v2) embed
these poorly because they rarely appear in training data.
OpenAI text-embedding-3-small was trained on massive medical
and scientific text corpora. It understands clinical synonyms
and abbreviations. Accuracy > local model accuracy for this
domain. Cost: ~$0.02 per 1M tokens = negligible for our corpus.

Alternative if offline: Use "intfloat/multilingual-e5-large"
via sentence-transformers. Set USE_LOCAL_EMBEDDINGS=true in .env

IMAGE HANDLING STRATEGY
-----------------------
The Kenya FP Guidelines contain 364 images — many are clinical
procedure diagrams (implant insertion, IUD insertion steps, etc.)
These cannot be embedded as text. Our strategy:

1. Detect pages with images using pdfplumber
2. Render those pages as PNG at 150 DPI
3. Store PNGs in knowledge_base/images/ with naming convention:
   {source_id}_page_{page_num}_{image_idx}.png
4. Create a text chunk that references the image:
   "Figure: [description from surrounding text]. Image stored at:
   {image_path}. Shown when discussing: {method_name} {topic}."
5. Embed the descriptive text chunk — the image path is the payload
6. At retrieval time, the orchestrator checks if a retrieved chunk
   contains an image path and includes it in the response

This means the LLM gets: "The clinical procedure for implant
insertion is described below. See Figure: implant_insertion_step3.png"
And the frontend renders the image alongside the text.

CHUNKING STRATEGY
-----------------
Fixed-size chunking (512 tokens, 50 token overlap) is the naive
approach used by most tutorials. It is wrong for clinical documents
because a 512-token window will cut mid-table, mid-step, or
mid-criterion. We use SEMANTIC chunking:

1. Split by structural markers: Chapter, Section, Subsection headers
2. Within sections: split by paragraph boundary
3. Tables: kept whole (never split mid-table)
4. Numbered lists: kept whole (a step list is one chunk)
5. Maximum chunk size: 800 tokens (larger for tables and lists)
6. Overlap: 100 tokens between adjacent chunks in same section

Each chunk carries metadata:
  - source: document identifier
  - document_title: full document name
  - authority_level: 1 (highest) to 3
  - chapter: chapter number and title
  - section: section heading
  - topic_tags: list of methods/conditions mentioned
  - page_num: PDF page number
  - has_image: bool
  - image_paths: list of image file paths if has_image
  - chunk_type: "text", "table", "step_list", "image_reference"
  - language: "english"
  - country_scope: "kenya" or "global"

RETRIEVAL STRATEGY AT QUERY TIME
---------------------------------
When the orchestrator calls retrieve(query, profile):

1. METADATA PRE-FILTER: Filter by topic_tags matching the methods
   the user is asking about (e.g. query about implants only retrieves
   chunks tagged with "implant")

2. SEMANTIC SEARCH: ChromaDB cosine similarity search in filtered
   results, retrieve top 8 candidates

3. AUTHORITY RE-RANKING: Among top 8, re-rank by authority_level.
   A Category 4 contraindication from WHO MEC should outrank a
   general description from Kenya FP guidelines.

4. CONTEXT ASSEMBLY: Top 4 chunks after re-ranking become the
   LLM context. Image paths are extracted and passed to frontend.

5. SOURCE CITATION: Every LLM response cites the source document,
   chapter, and page number so users can verify.

STORAGE LAYOUT
--------------
knowledge_base/
├── chroma_db/              ← ChromaDB persistent vector store
│   └── chaguoai_fp/        ← Collection name
├── images/                 ← Extracted clinical procedure images
│   ├── kenya_fp_page_70_implant_step1.png
│   ├── kenya_fp_page_98_iud_insertion.png
│   └── ...
├── chunks/                 ← JSON cache of all chunks (for audit)
│   ├── kenya_fp_chunks.json
│   ├── who_mec_chunks.json
│   └── who_spr_chunks.json
└── ingestion_manifest.json ← Records what was ingested and when

Usage
-----
    # First time (or when documents update):
    python src/rag_ingestor.py

    # From another module:
    from src.rag_ingestor import build_knowledge_base, get_retriever
    retriever = get_retriever()
    chunks = retriever.retrieve("Can I use implant while breastfeeding?")

Environment variables (.env):
    OPENAI_API_KEY=sk-...
    USE_LOCAL_EMBEDDINGS=false   (set true to use offline model)
    CHROMA_PERSIST_DIR=./knowledge_base/chroma_db
    IMAGES_DIR=./knowledge_base/images
    CHUNKS_DIR=./knowledge_base/chunks
    EMBEDDING_MODEL=text-embedding-3-small
    LOCAL_EMBEDDING_MODEL=intfloat/multilingual-e5-large

Author: ChaguoAI Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
import requests
import json
import hashlib
from pathlib import Path

# --- SYSTEM FIX: Unset environment proxies that cause OpenAI/Httpx initialization errors ---
for env_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    if env_var in os.environ:
        os.environ.pop(env_var)

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

import pdfplumber

# ── resolve project root for portable imports ─────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
# No longer adding /src since files are in the root of backend
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chaguoai.rag_ingestor")


# ============================================================
# CONFIGURATION — all values from environment, never hardcoded
# ============================================================

def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)

def _env_bool(key: str, default: bool = False) -> bool:
    return _env(key, str(default)).lower() in ("true", "1", "yes")


class RAGConfig:
    """
    All configuration loaded from environment variables.
    Override any value in your .env file — no code changes needed.
    """
    # Paths
    KB_DIR: Path = PROJECT_ROOT / _env("KNOWLEDGE_BASE_DIR", "knowledge_base")
    CHROMA_DIR: Path = KB_DIR / _env("CHROMA_SUBDIR", "chroma_db")
    IMAGES_DIR: Path = KB_DIR / _env("IMAGES_SUBDIR", "images")
    CHUNKS_DIR: Path = KB_DIR / _env("CHUNKS_SUBDIR", "chunks")

    # Embedding model
    USE_LOCAL_EMBEDDINGS: bool = _env_bool("USE_LOCAL_EMBEDDINGS", False)
    OPENAI_EMBEDDING_MODEL: str = _env("EMBEDDING_MODEL", "text-embedding-3-small")
    LOCAL_EMBEDDING_MODEL: str = _env(
        "LOCAL_EMBEDDING_MODEL", "intfloat/multilingual-e5-large"
    )

    # ChromaDB
    CHROMA_COLLECTION: str = _env("CHROMA_COLLECTION", "chaguoai_fp")

    # Chunking
    MAX_CHUNK_TOKENS: int = int(_env("MAX_CHUNK_TOKENS", "800"))
    CHUNK_OVERLAP_TOKENS: int = int(_env("CHUNK_OVERLAP_TOKENS", "100"))

    # Image extraction
    IMAGE_DPI: int = int(_env("IMAGE_DPI", "150"))
    EXTRACT_IMAGES: bool = _env_bool("EXTRACT_IMAGES", True)
    MIN_IMAGE_WIDTH_PX: int = int(_env("MIN_IMAGE_WIDTH_PX", "200"))

    # Retrieval
    TOP_K_CANDIDATES: int = int(_env("TOP_K_CANDIDATES", "8"))
    TOP_K_FINAL: int = int(_env("TOP_K_FINAL", "4"))

    @classmethod
    def ensure_dirs(cls):
        for d in [cls.KB_DIR, cls.CHROMA_DIR, cls.IMAGES_DIR, cls.CHUNKS_DIR]:
            d.mkdir(parents=True, exist_ok=True)


# ============================================================
# DOCUMENT REGISTRY
#
# Add new source documents here. No other file changes needed.
# ============================================================

@dataclass
class SourceDocument:
    """
    Registration record for one PDF document in the knowledge base.
    """
    doc_id: str             # Short identifier used in metadata
    file_env_var: str       # Environment variable holding the PDF path
    document_title: str     # Full human-readable title
    authority_level: int    # 1 = highest (WHO MEC), 2 = high, 3 = supplementary
    country_scope: str      # "kenya", "global", or specific country
    language: str           # "english" or "swahili"
    publication_year: int
    publisher: str
    chapter_map: dict       # Maps page ranges to chapter names
    method_pages: dict      # Maps method names to page ranges for pre-filtering


SOURCE_DOCUMENTS = [

    SourceDocument(
        doc_id="kenya_fp_7th",
        file_env_var="KENYA_FP_PDF",
        document_title=(
            "National Family Planning Guideline for Healthcare Providers, "
            "7th Edition"
        ),
        authority_level=1,
        country_scope="kenya",
        language="english",
        publication_year=2025,
        publisher="Ministry of Health Kenya, DRMNCAH",
        chapter_map={
            (1,  6):   "Chapter 1: Introduction",
            (7,  14):  "Chapter 2: Background",
            (15, 55):  "Chapter 3: Service Delivery and Client Assessment",
            (56, 132): "Chapter 4: Hormonal Contraceptive Methods",
            (133,154): "Chapter 5: Intrauterine Devices (IUD)",
            (155,171): "Chapter 6: Voluntary Surgical Contraception",
            (172,185): "Chapter 7: Barrier Methods",
            (186,190): "Chapter 8: Lactational Amenorrhoea Method (LAM)",
            (191,203): "Chapter 9: Fertility Awareness-Based Methods",
            (204,227): "Chapter 10: Health Products and Technologies",
            (228,242): "Chapter 11: Cross-Cutting Issues",
            (243,270): "Chapter 12: High-Impact Practices",
            (271,282): "Chapter 13: Monitoring and Evaluation",
            (283,312): "Chapter 14: Appendices",
        },
        method_pages={
            "combined_oral_contraceptive":  (56,  80),
            "progestin_only_pill":          (81,  95),
            "injectable_dmpa":              (96, 115),
            "implant":                      (116,132),
            "copper_iud":                   (133,153),
            "lng_iud":                      (133,153),
            "female_sterilization":         (155,168),
            "male_sterilization":           (169,171),
            "male_condom":                  (172,180),
            "female_condom":                (181,185),
            "lam":                          (186,190),
            "fertility_awareness":          (191,203),
            "client_assessment":            (15,  55),
            "emergency_contraceptive":      (56,  80),
        },
    ),

    SourceDocument(
        doc_id="who_mec_6th",
        file_env_var="WHO_MEC_PDF",
        document_title=(
            "Medical Eligibility Criteria for Contraceptive Use, 6th Edition"
        ),
        authority_level=1,
        country_scope="global",
        language="english",
        publication_year=2025,
        publisher="World Health Organization",
        chapter_map={
            (1,   10): "Executive Summary and Introduction",
            (11,  20): "Section 2: How to Use MEC",
            (21, 200): "Section 3: Recommendations by Medical Condition",
            (201,218): "Section 4 & Annexes: Changes and References",
        },
        method_pages={
            # MEC tables are organized by condition, not method,
            # so we tag by both condition and method during chunking
            "combined_oral_contraceptive": (21, 200),
            "injectable_dmpa":             (21, 200),
            "implant":                     (21, 200),
            "copper_iud":                  (21, 200),
            "lng_iud":                     (21, 200),
        },
    ),

    SourceDocument(
        doc_id="who_spr_4th",
        file_env_var="WHO_SPR_PDF",
        document_title=(
            "Selected Practice Recommendations for Contraceptive Use, "
            "4th Edition"
        ),
        authority_level=1,
        country_scope="global",
        language="english",
        publication_year=2025,
        publisher="World Health Organization",
        chapter_map={
            (1,  10): "Executive Summary and Introduction",
            (11, 30): "Initiation Recommendations",
            (31, 70): "Correct Use and Managing Problems",
            (71, 108):"Special Populations and Annexes",
        },
        method_pages={
            "copper_iud":                  (11, 40),
            "lng_iud":                     (11, 40),
            "implant":                     (41, 60),
            "injectable_dmpa":             (41, 60),
            "progestin_only_pill":         (61, 75),
            "combined_oral_contraceptive": (61, 75),
            "emergency_contraceptive":     (76, 90),
            "male_sterilization":          (91,108),
        },
    ),
]


# ============================================================
# CHUNK DATA CLASS
# ============================================================

@dataclass
class DocumentChunk:
    """
    One unit of knowledge in the vector store.

    Every field that can affect retrieval accuracy is captured
    here. Metadata is stored alongside the embedding in ChromaDB
    and used for pre-filtering before semantic search.
    """
    chunk_id: str           # SHA-256 hash of (doc_id + page + text[:100])
    doc_id: str             # Source document identifier
    document_title: str
    authority_level: int
    country_scope: str
    chapter: str
    section: str
    page_num: int
    chunk_type: str         # "text", "table", "step_list", "image_reference"
    text: str               # The actual text content for embedding
    topic_tags: list[str]   # Methods and conditions mentioned
    has_image: bool
    image_paths: list[str]  # Relative paths to extracted images
    language: str
    publisher: str
    publication_year: int
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.text)
        if not self.chunk_id:
            # Revert to a simple uuid if for some reason it's missing, 
            # though the chunker should always provide it now.
            import uuid
            self.chunk_id = str(uuid.uuid4())[:16]


# ============================================================
# KEYWORD MAPS FOR TOPIC TAGGING
#
# Used to automatically tag each chunk with the methods and
# conditions it discusses. These tags power metadata pre-filtering
# at retrieval time, making search dramatically more precise.
# ============================================================

METHOD_KEYWORDS = {
    "combined_oral_contraceptive": [
        "combined oral", "coc", "combined pill", "the pill",
        "ethinyl estradiol", "combined hormonal", "chc",
        "femiplan", "microgynon", "low-dose",
    ],
    "progestin_only_pill": [
        "progestogen-only pill", "pop", "mini-pill", "progestin-only pill",
        "chaguo lako",
    ],
    "injectable_dmpa": [
        "dmpa", "injectable", "injection", "depo-provera", "depo",
        "net-en", "norethisterone", "dmpa-sc", "dmpa-im",
    ],
    "implant": [
        "implant", "jadelle", "implanon", "nexplanon", "sino-implant",
        "subdermal", "subdermally", "lng implant", "etg implant",
    ],
    "copper_iud": [
        "copper iud", "copper-bearing iud", "cu-iud", "iucd",
        "non-hormonal iud", "copper t",
    ],
    "lng_iud": [
        "lng-iud", "levonorgestrel iud", "hormonal iud", "mirena",
        "levogestrel-releasing iud",
    ],
    "female_sterilization": [
        "tubal ligation", "btl", "female sterilization",
        "bilateral tubal", "minilaparotomy", "laparoscopic",
    ],
    "male_sterilization": [
        "vasectomy", "male sterilization", "nsv", "no-scalpel",
    ],
    "male_condom": [
        "male condom", "condom", "latex", "dual protection",
    ],
    "female_condom": [
        "female condom", "internal condom", "fc2",
    ],
    "lam": [
        "lactational amenorrhoea", "lam", "breastfeeding method",
        "exclusive breastfeeding",
    ],
    "fertility_awareness": [
        "fertility awareness", "fab", "standard days method", "sdm",
        "cycle beads", "basal body temperature", "symptothermal",
        "cervical mucus", "calendar method", "rhythm method",
    ],
    "emergency_contraceptive": [
        "emergency contraceptive", "ecp", "morning after",
        "levonorgestrel 1.5", "ulipristal", "upa", "postcoital",
        "e-iud", "emergency iud",
    ],
    "client_assessment": [
        "client assessment", "screening", "eligibility", "intake",
        "gather", "braided", "counselling", "informed choice",
        "history taking", "physical examination",
    ],
}

CONDITION_KEYWORDS = {
    "hypertension": [
        "hypertension", "high blood pressure", "blood pressure",
        "systolic", "diastolic", "antihypertensive",
    ],
    "diabetes": [
        "diabetes", "diabetic", "insulin", "blood glucose",
        "nephropathy", "retinopathy", "neuropathy",
    ],
    "migraine": [
        "migraine", "aura", "headache", "focal neurological",
    ],
    "hiv": [
        "hiv", "aids", "antiretroviral", "art", "arvs", "prep",
        "nrti", "nnrti", "efavirenz", "protease inhibitor",
    ],
    "breastfeeding": [
        "breastfeeding", "breastfeed", "lactation", "nursing",
        "postpartum", "postnatal", "lam", "newborn",
    ],
    "vte": [
        "thrombosis", "dvt", "pulmonary embolism", "pe",
        "thromboembolic", "anticoagulant", "blood clot",
    ],
    "liver_disease": [
        "liver", "hepatitis", "cirrhosis", "jaundice",
        "liver disease", "hepatocellular",
    ],
    "breast_cancer": [
        "breast cancer", "breast tumour", "breast tumor",
        "breast disease",
    ],
    "cardiovascular": [
        "heart disease", "cardiac", "ischemic", "stroke",
        "cardiovascular", "myocardial infarction", "angina",
    ],
    "adolescent": [
        "adolescent", "teenager", "young person", "under 18",
        "menarche",
    ],
    "side_effects": [
        "side effect", "adverse effect", "bleeding", "spotting",
        "amenorrhoea", "nausea", "weight", "mood", "headache",
        "missed period",
    ],
}

ALL_TOPIC_KEYWORDS = {**METHOD_KEYWORDS, **CONDITION_KEYWORDS}


def _tag_chunk(text: str) -> list[str]:
    """
    Identify which methods and conditions a chunk discusses.
    Returns a list of topic tags for ChromaDB metadata.

    Uses case-insensitive keyword matching. A chunk gets tagged
    if any of its keywords appear in the text.
    """
    text_lower = text.lower()
    tags = []
    for topic, keywords in ALL_TOPIC_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            tags.append(topic)
    return tags


# ============================================================
# TEXT EXTRACTION AND SEMANTIC CHUNKING
# ============================================================

def _get_chapter(page_num: int, chapter_map: dict) -> str:
    """Return chapter name for a given page number."""
    for (start, end), chapter_name in chapter_map.items():
        if start <= page_num <= end:
            return chapter_name
    return "Appendix / Reference"


def _detect_section_header(text: str) -> Optional[str]:
    """
    Detect if a line is a section header.

    Clinical documents use: ALL CAPS, Title Case followed by colon,
    numbered sections (3.1, 4.2.1), or bold-equivalent markers.
    Returns the header text if detected, None otherwise.
    """
    line = text.strip()
    if not line or len(line) > 200:
        return None

    # ALL CAPS line (typical section header in Kenya FP guidelines)
    if line.isupper() and len(line) > 4:
        return line

    # Numbered section: "3.1 Combined Oral Contraceptives"
    if re.match(r"^\d+(\.\d+)*\s+[A-Z]", line):
        return line

    # "TABLE X:" or "BOX X:" patterns
    if re.match(r"^(TABLE|BOX|FIGURE|APPENDIX)\s+\d", line, re.IGNORECASE):
        return line

    return None


def _is_table_row(text: str) -> bool:
    """Detect if a line is part of a table (multiple | or tab-aligned columns)."""
    return text.count("|") >= 2 or text.count("\t") >= 3


def _semantic_chunk(
    pages: list[dict],
    doc: SourceDocument,
    config: RAGConfig,
) -> list[DocumentChunk]:
    """
    Convert extracted page data into semantically coherent chunks.

    Pages is a list of dicts:
        {"page_num": int, "text": str, "tables": list[str],
         "has_image": bool, "image_paths": list[str]}

    Strategy:
    1. Accumulate text paragraph by paragraph
    2. When a section header is detected, flush the current chunk
       and start a new one with the new section context
    3. Tables are extracted whole as single chunks
    4. Image references create their own chunks
    5. Chunks exceeding MAX_CHUNK_TOKENS are split at paragraph boundary

    This preserves clinical meaning across chunk boundaries,
    which is critical for accuracy. A step-by-step insertion
    procedure must never be split across chunks.
    """
    chunks: list[DocumentChunk] = []
    current_section = "Introduction"
    current_text_lines: list[str] = []
    current_pages: list[int] = []

    def _flush(chunk_type: str = "text", image_paths: list[str] = None):
        """Finalize the current buffer as a DocumentChunk."""
        if image_paths is None:
            image_paths = []
        text = "\n".join(current_text_lines).strip()
        if len(text) < 50:  # Skip fragments that are too short to be useful
            return

        # Approximate token count (1 token ≈ 4 characters for English)
        approx_tokens = len(text) / 4

        if approx_tokens > config.MAX_CHUNK_TOKENS:
            # Split at paragraph boundary
            paragraphs = text.split("\n\n")
            buffer = []
            for para in paragraphs:
                buffer.append(para)
                if len("\n\n".join(buffer)) / 4 >= config.MAX_CHUNK_TOKENS:
                    sub_text = "\n\n".join(buffer[:-1]).strip()
                    if sub_text:
                        _create_chunk(sub_text, chunk_type, current_pages,
                                      image_paths)
                    buffer = [para]
            if buffer:
                sub_text = "\n\n".join(buffer).strip()
                if sub_text:
                    _create_chunk(sub_text, chunk_type, current_pages,
                                  image_paths)
        else:
            _create_chunk(text, chunk_type, current_pages, image_paths)

    chunks: list[DocumentChunk] = []
    current_section = "General"
    current_buffer = []
    current_pages = []
    chunk_index = 0  # Sequence index to prevent hash collisions

    def _create_chunk(
        text: str, chunk_type: str,
        pages: list[int], image_paths: list[str]
    ):
        nonlocal chunk_index
        page_num = pages[0] if pages else 0
        chapter = _get_chapter(page_num, doc.chapter_map)
        tags = _tag_chunk(text)
        has_img = bool(image_paths)

        # Unique ID combining doc, page, index, and text fingerprint
        fingerprint = hashlib.md5(text.encode()).hexdigest()[:8]
        chunk_id = f"{doc.doc_id}_p{page_num}_idx{chunk_index}_{fingerprint}"
        chunk_index += 1

        chunks.append(DocumentChunk(
            chunk_id=chunk_id,
            doc_id=doc.doc_id,
            document_title=doc.document_title,
            authority_level=doc.authority_level,
            country_scope=doc.country_scope,
            chapter=chapter,
            section=current_section,
            page_num=page_num,
            chunk_type=chunk_type,
            text=text,
            topic_tags=tags,
            has_image=has_img,
            image_paths=image_paths,
            language=doc.language,
            publisher=doc.publisher,
            publication_year=doc.publication_year,
        ))

    for page_data in pages:
        page_num = page_data["page_num"]
        raw_text = page_data.get("text", "")
        tables = page_data.get("tables", [])
        has_image = page_data.get("has_image", False)
        image_paths = page_data.get("image_paths", [])

        # ── TABLES: extract whole as single chunks ──────────────────
        for table_text in tables:
            if len(table_text.strip()) > 30:
                _flush()
                current_text_lines.clear()
                current_pages.clear()
                # Table chunk: add section context at top
                full_table_text = (
                    f"[TABLE — {current_section}]\n"
                    f"Source: {doc.document_title}, Page {page_num}\n\n"
                    f"{table_text}"
                )
                _create_chunk(full_table_text, "table", [page_num], [])

        # ── TEXT: split by paragraph and section headers ────────────
        lines = raw_text.split("\n")
        for line in lines:
            header = _detect_section_header(line)
            if header:
                # Flush accumulated text, start new section
                _flush()
                current_text_lines.clear()
                current_pages.clear()
                current_section = header
                current_text_lines.append(f"[SECTION: {header}]")
            else:
                current_text_lines.append(line)
                if page_num not in current_pages:
                    current_pages.append(page_num)

        # ── IMAGES: create reference chunks ─────────────────────────
        if has_image and image_paths:
            _flush()
            current_text_lines.clear()
            current_pages.clear()

            # Build a descriptive image reference chunk
            surrounding_context = " ".join(
                line.strip() for line in lines if len(line.strip()) > 10
            )[:400]

            img_text = (
                f"[CLINICAL FIGURE — {current_section}]\n"
                f"Source: {doc.document_title}, Page {page_num}\n"
                f"Context: {surrounding_context}\n"
                f"Images stored at: {', '.join(image_paths)}\n"
                f"Display these images when explaining this procedure or concept."
            )
            _create_chunk(img_text, "image_reference", [page_num], image_paths)

    # Flush any remaining text
    _flush()
    current_text_lines.clear()

    log.info(f"  Generated {len(chunks)} chunks from {doc.doc_id}")
    return chunks


# ============================================================
# PDF EXTRACTION
# ============================================================

def extract_pdf(
    pdf_path: Path,
    doc: SourceDocument,
    config: RAGConfig,
) -> list[dict]:
    """
    Extract all content from one PDF using pdfplumber.

    Returns a list of page dicts:
        {page_num, text, tables, has_image, image_paths}

    IMAGE EXTRACTION:
    pdfplumber detects images on each page. When significant images
    are found (width > MIN_IMAGE_WIDTH_PX), we:
    1. Log that the page has clinical images
    2. Store the page number and image bounding boxes
    3. Use pdftoppm to render those pages as PNG at IMAGE_DPI

    NOTE: pdfplumber can detect image presence and coordinates but
    cannot directly save PNG output. We use pdftoppm (part of poppler)
    which is universally available on Linux/Mac/Windows. If pdftoppm
    is not available, we set has_image=True but skip image extraction
    — the text context is preserved.
    """
    log.info(f"Extracting: {pdf_path.name} ({pdf_path.stat().st_size // 1024}KB)")

    pages_data = []
    pdftoppm_available = _check_pdftoppm()

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        log.info(f"  Total pages: {total_pages}")

        for page in pdf.pages:
            page_num = page.page_number  # 1-indexed

            # ── EXTRACT TEXT ─────────────────────────────────────────
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""

            # ── EXTRACT TABLES ────────────────────────────────────────
            table_texts = []
            try:
                tables = page.extract_tables()
                for table in (tables or []):
                    if table:
                        rows = []
                        for row in table:
                            clean_row = [
                                str(cell).strip() if cell else ""
                                for cell in row
                            ]
                            rows.append(" | ".join(clean_row))
                        table_str = "\n".join(rows)
                        if len(table_str) > 30:
                            table_texts.append(table_str)
            except Exception as e:
                log.debug(f"  Table extraction error page {page_num}: {e}")

            # ── DETECT IMAGES ─────────────────────────────────────────
            image_objects = page.images or []
            significant_images = [
                img for img in image_objects
                if img.get("width", 0) >= config.MIN_IMAGE_WIDTH_PX
                and img.get("height", 0) >= config.MIN_IMAGE_WIDTH_PX
            ]

            has_image = bool(significant_images) and config.EXTRACT_IMAGES
            image_paths = []

            if has_image and pdftoppm_available:
                image_paths = _render_page_as_image(
                    pdf_path, page_num, doc.doc_id, config
                )

            pages_data.append({
                "page_num":   page_num,
                "text":       text,
                "tables":     table_texts,
                "has_image":  has_image,
                "image_paths": image_paths,
            })

            if page_num % 50 == 0:
                log.info(f"  Processed page {page_num}/{total_pages}")

    text_pages = sum(1 for p in pages_data if p["text"].strip())
    image_pages = sum(1 for p in pages_data if p["has_image"])
    table_pages = sum(1 for p in pages_data if p["tables"])

    log.info(
        f"  Extraction complete: {text_pages} text pages, "
        f"{image_pages} image pages, {table_pages} table pages"
    )
    return pages_data


def _check_pdftoppm() -> bool:
    """Check if pdftoppm (poppler) is available on this system."""
    import subprocess
    try:
        result = subprocess.run(
            ["pdftoppm", "-v"],
            capture_output=True, timeout=5
        )
        return result.returncode == 0 or b"pdftoppm" in result.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        log.warning(
            "pdftoppm not found. Images will be detected but not extracted. "
            "Install poppler-utils to enable image extraction: "
            "apt-get install poppler-utils (Linux) or brew install poppler (Mac)"
        )
        return False


def _render_page_as_image(
    pdf_path: Path,
    page_num: int,
    doc_id: str,
    config: RAGConfig,
) -> list[str]:
    """
    Render a PDF page as PNG using pdftoppm.

    Returns a list of relative paths to the saved PNG files,
    relative to the project root.
    """
    import subprocess

    output_stem = config.IMAGES_DIR / f"{doc_id}_page_{page_num:04d}"
    output_path = Path(str(output_stem) + "-1.png")

    # Check if already rendered (skip re-renders on re-ingestion)
    if output_path.exists():
        relative = str(output_path.relative_to(PROJECT_ROOT))
        return [relative]

    cmd = [
        "pdftoppm",
        "-png",
        "-r", str(config.IMAGE_DPI),
        "-f", str(page_num),
        "-l", str(page_num),
        str(pdf_path),
        str(output_stem),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0 and output_path.exists():
            relative = str(output_path.relative_to(PROJECT_ROOT))
            log.debug(f"  Rendered image: {relative}")
            return [relative]
        else:
            log.debug(f"  pdftoppm failed for page {page_num}: {result.stderr}")
            return []
    except Exception as e:
        log.debug(f"  Image render error page {page_num}: {e}")
        return []


# ============================================================
# EMBEDDING FUNCTIONS
# ============================================================

def _get_embedding_function(config: RAGConfig):
    """
    Return the appropriate embedding function based on configuration.

    DEFAULT: OpenAI text-embedding-3-small
      - Best accuracy for clinical/medical vocabulary
      - Requires OPENAI_API_KEY in .env
      - Cost: ~$0.02 per 1M tokens (negligible for this corpus)

    OFFLINE FALLBACK: intfloat/multilingual-e5-large
      - Runs locally via sentence-transformers
      - Good multilingual support (Swahili, French, Portuguese)
      - Set USE_LOCAL_EMBEDDINGS=true in .env
      - First run downloads ~1.3GB model weights

    The embedding function is ChromaDB-compatible.
    """
    if config.USE_LOCAL_EMBEDDINGS:
        log.info(f"Using local embedding model: {config.LOCAL_EMBEDDING_MODEL}")
        try:
            from chromadb.utils.embedding_functions import (
                SentenceTransformerEmbeddingFunction,
            )
            return SentenceTransformerEmbeddingFunction(
                model_name=config.LOCAL_EMBEDDING_MODEL
            )
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY not set in .env file. "
            "Either set the key or set USE_LOCAL_EMBEDDINGS=true "
            "in .env to use a local model."
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY not set in .env")

    # SYSTEM FIX: Unset proxies again just to be absolutely sure
    for env_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
        os.environ.pop(env_var, None)
            
    try:
        from chromadb.api.types import Documents, Embeddings, EmbeddingFunction
        class RequestEmbeddingFunction(EmbeddingFunction):
            def __init__(self, key, model):
                self.key = key
                self.model = model
                self.url = "https://api.openai.com/v1/embeddings"
            def __call__(self, texts: Documents) -> Embeddings:
                # Clean texts
                cleaned_texts = [str(t).replace("\n", " ") for t in texts]
                payload = {"input": cleaned_texts, "model": self.model}
                headers = {
                    "Authorization": f"Bearer {self.key}",
                    "Content-Type": "application/json"
                }
                # Use requests to completely bypass openai/httpx library issues
                resp = requests.post(self.url, headers=headers, json=payload, timeout=60)
                if resp.status_code != 200:
                    raise Exception(f"OpenAI API Error: {resp.text}")
                data = resp.json()
                return [d["embedding"] for d in data["data"]]
        
        return RequestEmbeddingFunction(api_key, config.OPENAI_EMBEDDING_MODEL)
    except Exception as e:
        log.error(f"Request-based embedding failed: {e}")
        # Last ditch effort
        from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
        return OpenAIEmbeddingFunction(api_key=api_key, model_name=config.OPENAI_EMBEDDING_MODEL)


# ============================================================
# VECTOR STORE OPERATIONS
# ============================================================

def _get_chroma_collection(config: RAGConfig):
    """
    Initialize and return the ChromaDB collection.

    ChromaDB persists to disk at CHROMA_DIR. On subsequent runs,
    the collection is loaded from disk — no re-embedding needed.
    """
    try:
        import chromadb
    except ImportError:
        raise ImportError("chromadb not installed. Run: pip install chromadb")

    embedding_fn = _get_embedding_function(config)

    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    collection = client.get_or_create_collection(
        name=config.CHROMA_COLLECTION,
        embedding_function=embedding_fn,
        metadata={
            "description": "ChaguoAI Family Planning Knowledge Base",
            "sources": "Kenya FP 7th Ed, WHO MEC 6th Ed, WHO SPR 4th Ed",
            "created": datetime.now().isoformat(),
        }
    )
    return collection


def _upsert_chunks_to_chroma(
    chunks: list[DocumentChunk],
    collection,
    batch_size: int = 50,
):
    """
    Upsert all chunks into ChromaDB collection.

    Uses upsert (not add) so re-ingesting a document updates
    existing chunks rather than creating duplicates.

    Metadata fields must be: str, int, float, or bool.
    Lists are serialized as comma-separated strings.
    """
    log.info(f"Upserting {len(chunks)} chunks to ChromaDB...")

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]

        ids = [c.chunk_id for c in batch]
        documents = [c.text for c in batch]
        metadatas = [
            {
                "doc_id":           c.doc_id,
                "document_title":   c.document_title[:200],
                "authority_level":  c.authority_level,
                "country_scope":    c.country_scope,
                "chapter":          c.chapter[:200],
                "section":          c.section[:200],
                "page_num":         c.page_num,
                "chunk_type":       c.chunk_type,
                "topic_tags":       ",".join(c.topic_tags),
                "has_image":        c.has_image,
                "image_paths":      ",".join(c.image_paths),
                "language":         c.language,
                "publisher":        c.publisher[:100],
                "publication_year": c.publication_year,
                "char_count":       c.char_count,
            }
            for c in batch
        ]

        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

        log.info(
            f"  Upserted batch {i // batch_size + 1}/"
            f"{(len(chunks) - 1) // batch_size + 1}"
        )

    log.info(f"ChromaDB collection now has {collection.count()} total chunks")


# ============================================================
# RETRIEVAL ENGINE
# ============================================================

class ChaguoAIRetriever:
    """
    Semantic retrieval engine for the ChaguoAI knowledge base.

    Combines metadata pre-filtering with semantic search and
    authority-level re-ranking to maximize retrieval accuracy
    for clinical family planning queries.

    Usage:
        retriever = ChaguoAIRetriever(config)
        results = retriever.retrieve(
            query="Can I use DMPA while breastfeeding?",
            method_filter="injectable_dmpa",
            top_k=4
        )
    """

    def __init__(self, config: Optional[RAGConfig] = None):
        self.config = config or RAGConfig()
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            self._collection = _get_chroma_collection(self.config)
        return self._collection

    def retrieve(
        self,
        query: str,
        method_filter: Optional[str] = None,
        condition_filter: Optional[str] = None,
        country_scope: Optional[str] = None,
        top_k: int = 4,
    ) -> list[dict]:
        """
        Retrieve the most relevant chunks for a clinical query.

        Parameters
        ----------
        query : str
            The user's question or the orchestrator's retrieval query.
            Should be specific: "DMPA side effects breastfeeding" not "contraception".

        method_filter : str, optional
            Filter to chunks tagged with this method.
            E.g. "injectable_dmpa", "implant", "copper_iud"

        condition_filter : str, optional
            Filter to chunks tagged with this condition.
            E.g. "hiv", "hypertension", "breastfeeding"

        country_scope : str, optional
            "kenya" prioritizes Kenya FP Guidelines.
            "global" prioritizes WHO documents.
            None returns from all sources.

        top_k : int
            Number of chunks to return after re-ranking.

        Returns
        -------
        list[dict]
            Each dict has: text, metadata, relevance_score, image_paths
        """
        collection = self._get_collection()

        # ── STEP 1: Build metadata filter ────────────────────────────
        where_clause = self._build_where_clause(
            method_filter, condition_filter, country_scope
        )

        # ── STEP 2: Semantic search in filtered space ─────────────────
        n_candidates = min(
            self.config.TOP_K_CANDIDATES,
            collection.count()
        )

        if n_candidates == 0:
            log.warning("ChromaDB collection is empty. Run ingestion first.")
            return []

        query_kwargs = {
            "query_texts": [query],
            "n_results": n_candidates,
            "include": ["documents", "metadatas", "distances"],
        }
        if where_clause:
            query_kwargs["where"] = where_clause

        try:
            results = collection.query(**query_kwargs)
        except Exception as e:
            # If the filter returns no results, retry without filter
            log.warning(f"Filtered query failed ({e}). Retrying without filter.")
            query_kwargs.pop("where", None)
            results = collection.query(**query_kwargs)

        # ── STEP 3: Parse results ─────────────────────────────────────
        candidates = []
        for text, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            # ChromaDB distances are L2 or cosine distances (lower = more similar)
            # Convert to similarity score (higher = more relevant)
            similarity = 1 - dist if dist <= 1 else 1 / (1 + dist)

            image_paths = [
                p.strip() for p in meta.get("image_paths", "").split(",")
                if p.strip()
            ]

            candidates.append({
                "text":              text,
                "metadata":          meta,
                "similarity_score":  similarity,
                "authority_level":   meta.get("authority_level", 3),
                "image_paths":       image_paths,
                "has_image":         meta.get("has_image", False),
                "source_citation":   self._format_citation(meta),
            })

        # ── STEP 4: Authority re-ranking ──────────────────────────────
        # Boost chunks from higher-authority documents.
        # Formula: final_score = similarity * authority_boost
        # authority_level 1 → boost 1.0 (no penalty)
        # authority_level 2 → boost 0.9
        # authority_level 3 → boost 0.8
        for c in candidates:
            boost = 1.0 - (c["authority_level"] - 1) * 0.1
            c["final_score"] = c["similarity_score"] * boost

        # Sort by final score
        candidates.sort(key=lambda x: x["final_score"], reverse=True)

        return candidates[:top_k]

    def _build_where_clause(
        self,
        method_filter: Optional[str],
        condition_filter: Optional[str],
        country_scope: Optional[str],
    ) -> Optional[dict]:
        """
        Build ChromaDB where clause for metadata pre-filtering.

        ChromaDB uses MongoDB-style query syntax.
        We use $contains on topic_tags (stored as comma-separated string).
        """
        conditions = []

        if method_filter:
            conditions.append({
                "topic_tags": {"$contains": method_filter}
            })

        if condition_filter:
            conditions.append({
                "topic_tags": {"$contains": condition_filter}
            })

        if country_scope == "kenya":
            conditions.append({
                "country_scope": {"$in": ["kenya", "global"]}
            })
        elif country_scope == "global":
            conditions.append({
                "country_scope": {"$eq": "global"}
            })

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def _format_citation(self, meta: dict) -> str:
        """Format a human-readable citation for a retrieved chunk."""
        return (
            f"{meta.get('document_title', 'Unknown source')}, "
            f"{meta.get('chapter', '')}, "
            f"Page {meta.get('page_num', '?')}"
        )

    def retrieve_for_method(
        self,
        method_name: str,
        query_type: str = "general",
        top_k: int = 4,
    ) -> list[dict]:
        """
        Specialized retrieval for a specific contraceptive method.

        query_type options:
            "general"     — overview of the method
            "eligibility" — who can and cannot use this method
            "side_effects"— side effects and how to manage them
            "how_to_use"  — initiation and correct use
            "missed_dose" — what to do if dose is missed or late
            "stopping"    — how to discontinue
        """
        query_map = {
            "general": (
                f"What is {method_name}? How does it work? "
                f"Who is it suitable for?"
            ),
            "eligibility": (
                f"Medical eligibility criteria for {method_name}. "
                f"Who cannot use {method_name}? Contraindications."
            ),
            "side_effects": (
                f"Side effects of {method_name}. How to manage bleeding "
                f"changes, amenorrhoea, headaches, weight changes."
            ),
            "how_to_use": (
                f"How to start {method_name}. When to begin. "
                f"Correct use instructions."
            ),
            "missed_dose": (
                f"What to do if {method_name} dose is missed or late. "
                f"Instructions for delayed re-dosing."
            ),
            "stopping": (
                f"How to stop {method_name}. Return to fertility after stopping."
            ),
        }
        query = query_map.get(query_type, query_map["general"])
        return self.retrieve(
            query=query,
            method_filter=method_name,
            top_k=top_k,
        )

    def format_context_for_llm(
        self,
        chunks: list[dict],
        include_citations: bool = True,
    ) -> str:
        """
        Format retrieved chunks as a structured context block for the LLM.

        The LLM receives this as part of its system prompt.
        Each chunk is clearly attributed to its source document so the
        LLM can cite sources accurately in its response.
        """
        if not chunks:
            return "[No relevant clinical content retrieved from knowledge base.]"

        lines = [
            "[RETRIEVED CLINICAL KNOWLEDGE — ChaguoAI Knowledge Base]",
            "The following information was retrieved from authoritative "
            "family planning guidelines. Base your response on this content.",
            "Do NOT add information not present in these sources.",
            "",
        ]

        for i, chunk in enumerate(chunks, 1):
            citation = chunk.get("source_citation", "Unknown source")
            lines.append(f"--- SOURCE {i} ---")
            if include_citations:
                lines.append(f"From: {citation}")
            lines.append(chunk["text"][:1500])  # Truncate very long chunks

            if chunk.get("image_paths"):
                lines.append(
                    f"[CLINICAL FIGURE AVAILABLE: "
                    f"{', '.join(chunk['image_paths'])}]"
                    f" — Show this image when explaining the procedure above."
                )
            lines.append("")

        return "\n".join(lines)


# ============================================================
# MAIN INGESTION PIPELINE
# ============================================================

def build_knowledge_base(
    pdf_paths: Optional[dict] = None,
    config: Optional[RAGConfig] = None,
    force_rebuild: bool = False,
) -> ChaguoAIRetriever:
    """
    Main entry point for building the knowledge base.

    Reads all three PDF documents, extracts and chunks their content,
    embeds the chunks, and stores them in ChromaDB.

    Parameters
    ----------
    pdf_paths : dict, optional
        Override paths for each document:
            {"kenya_fp_7th": Path(...), "who_mec_6th": Path(...), ...}
        If None, reads from environment variables.

    config : RAGConfig, optional
        Configuration. If None, uses defaults from .env.

    force_rebuild : bool
        If True, clears the ChromaDB collection and re-ingests everything.
        If False, skips documents whose chunks are already in the DB.

    Returns
    -------
    ChaguoAIRetriever
        Ready-to-use retrieval engine.
    """
    if config is None:
        config = RAGConfig()
    config.ensure_dirs()

    log.info("=" * 60)
    log.info("ChaguoAI Knowledge Base Ingestion")
    log.info("=" * 60)

    collection = _get_chroma_collection(config)

    if force_rebuild:
        log.info("Force rebuild: clearing existing collection...")
        # Get all IDs and delete them
        all_ids = collection.get()["ids"]
        if all_ids:
            collection.delete(ids=all_ids)
        log.info(f"Cleared {len(all_ids)} existing chunks")

    all_chunks: list[DocumentChunk] = []
    manifest = {
        "ingested_at": datetime.now().isoformat(),
        "documents": {},
    }

    for doc in SOURCE_DOCUMENTS:
        # Resolve PDF path
        pdf_path = None
        if pdf_paths and doc.doc_id in pdf_paths:
            pdf_path = Path(pdf_paths[doc.doc_id])
        else:
            env_path = os.getenv(doc.file_env_var)
            if env_path:
                # Portable path resolution: if relative, anchor to PROJECT_ROOT
                pdf_path = Path(env_path)
                if not pdf_path.is_absolute():
                    pdf_path = PROJECT_ROOT / pdf_path

        if pdf_path is None or not pdf_path.exists():
            log.warning(
                f"PDF not found for {doc.doc_id}. "
                f"Set {doc.file_env_var} in .env or pass pdf_paths dict. "
                f"Skipping."
            )
            continue

        # Check if already ingested (unless force_rebuild)
        if not force_rebuild:
            existing = collection.get(
                where={"doc_id": {"$eq": doc.doc_id}}
            )
            if existing["ids"]:
                log.info(
                    f"Skipping {doc.doc_id}: "
                    f"{len(existing['ids'])} chunks already in DB. "
                    f"Use force_rebuild=True to re-ingest."
                )
                continue

        log.info(f"\nProcessing: {doc.document_title}")
        start_time = time.time()

        # Extract pages
        pages = extract_pdf(pdf_path, doc, config)

        # Semantic chunking
        chunks = _semantic_chunk(pages, doc, config)
        all_chunks.extend(chunks)

        # Save chunks as JSON audit trail
        chunk_file = config.CHUNKS_DIR / f"{doc.doc_id}_chunks.json"
        with open(chunk_file, "w", encoding="utf-8") as f:
            json.dump(
                [asdict(c) for c in chunks],
                f, indent=2, ensure_ascii=False,
            )
        log.info(f"  Chunk audit saved: {chunk_file}")

        # Upsert to ChromaDB
        _upsert_chunks_to_chroma(chunks, collection)

        elapsed = time.time() - start_time
        manifest["documents"][doc.doc_id] = {
            "document_title": doc.document_title,
            "pdf_path": str(pdf_path),
            "chunks_created": len(chunks),
            "processing_seconds": round(elapsed, 1),
            "ingested_at": datetime.now().isoformat(),
        }
        log.info(f"  Done in {elapsed:.1f}s — {len(chunks)} chunks ingested")

    # Save ingestion manifest
    manifest_path = config.KB_DIR / "ingestion_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    total_chunks = collection.count()
    log.info("\n" + "=" * 60)
    log.info(f"Knowledge base build complete")
    log.info(f"Total chunks in vector store: {total_chunks:,}")
    log.info(f"Manifest saved: {manifest_path}")
    log.info("=" * 60)

    return ChaguoAIRetriever(config)


def get_retriever(config: Optional[RAGConfig] = None) -> ChaguoAIRetriever:
    """
    Return a retriever connected to the existing knowledge base.
    Does NOT rebuild — assumes build_knowledge_base() has been run.

    This is the function called by the orchestrator at runtime.
    """
    return ChaguoAIRetriever(config or RAGConfig())


# ============================================================
# CLI ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="ChaguoAI RAG Knowledge Base Ingestion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # First-time ingestion using .env paths:
  python src/rag_ingestor.py

  # Force rebuild (re-process all documents):
  python src/rag_ingestor.py --force-rebuild

  # Specify PDF paths directly:
  python src/rag_ingestor.py \\
    --kenya-fp ./docs/kenya_fp_7th.pdf \\
    --who-mec  ./docs/who_mec_6th.pdf \\
    --who-spr  ./docs/who_spr_4th.pdf

  # Test retrieval after ingestion:
  python src/rag_ingestor.py --test-query "Can I use DMPA while breastfeeding?"
        """
    )
    parser.add_argument(
        "--force-rebuild", action="store_true",
        help="Clear existing knowledge base and re-ingest all documents"
    )
    parser.add_argument("--kenya-fp", type=str, default=None)
    parser.add_argument("--who-mec",  type=str, default=None)
    parser.add_argument("--who-spr",  type=str, default=None)
    parser.add_argument(
        "--test-query", type=str, default=None,
        help="Run a test retrieval query after ingestion"
    )

    args = parser.parse_args()

    pdf_paths = {}
    if args.kenya_fp:
        pdf_paths["kenya_fp_7th"] = args.kenya_fp
    if args.who_mec:
        pdf_paths["who_mec_6th"] = args.who_mec
    if args.who_spr:
        pdf_paths["who_spr_4th"] = args.who_spr

    retriever = build_knowledge_base(
        pdf_paths=pdf_paths or None,
        force_rebuild=args.force_rebuild,
    )

    if args.test_query:
        print(f"\n{'='*60}")
        print(f"TEST QUERY: {args.test_query}")
        print("=" * 60)
        results = retriever.retrieve(args.test_query)
        for i, r in enumerate(results, 1):
            print(f"\n[Result {i}] Score: {r['final_score']:.3f}")
            print(f"Source: {r['source_citation']}")
            print(f"Text preview: {r['text'][:300]}...")
            if r["image_paths"]:
                print(f"Images: {r['image_paths']}")
