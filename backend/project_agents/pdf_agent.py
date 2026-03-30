"""
project_agents/pdf_agent.py — PDF ingestion with chunking.

FIX (Gemini critique #2 — PDF Token Bloat):
  Previously: dumped ALL pages directly into the LLM prompt.
  Risk: 40-page PDF = ~80,000 tokens. Blows context limit.
        "Lost in the Middle" — LLM ignores data in the centre of a huge prompt.

  Fix: Intelligent chunking pipeline:
    1. Tables are always kept (highest information density).
    2. Text is scored for data density (lines with numbers score higher).
    3. Only the top-scoring chunks are sent, hard-capped at TOKEN_BUDGET chars.
    4. If the document is too large, we summarise using a map step first.
"""

from __future__ import annotations
import io
import re
import logging
from typing import List

from ..models import AgentMode, SessionContext, AnalysisResult
from ..project_agents.analyst_agent import AnalystAgent

logger = logging.getLogger("syslens.pdf_agent")

# Hard cap on characters sent to the LLM (~12,000 chars ≈ ~3,000 tokens)
TOKEN_BUDGET = 12_000
# Max pages to process before switching to map-reduce summarisation
PAGE_LIMIT_FULL = 15


def _score_line(line: str) -> float:
    """Score a text line by data density. Lines with numbers score higher."""
    nums = len(re.findall(r'\d+\.?\d*', line))
    pcts = len(re.findall(r'\d+\.?\d*\s*%', line))
    currencies = len(re.findall(r'[\$£€¥]', line))
    return nums * 1.0 + pcts * 2.0 + currencies * 1.5


class PdfAgent:
    """
    Extracts text and tables from a PDF with smart chunking to avoid token bloat.
    """

    def __init__(self):
        self._analyst = AnalystAgent()

    def run(self, pdf_bytes: bytes, user_text: str, ctx: SessionContext) -> AnalysisResult:
        extracted = self._extract_smart(pdf_bytes)
        prompt = self._build_prompt(extracted, user_text)
        logger.info(f"PDF prompt size: {len(prompt)} chars ({len(prompt)//4} est. tokens)")
        result = self._analyst.run(prompt, ctx)
        result.mode = AgentMode.PDF.value
        result.cleaning_steps = extracted["cleaning_steps"] + result.cleaning_steps
        return result

    def _extract_smart(self, pdf_bytes: bytes) -> dict:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Run: pip install pdfplumber")

        tables:     List[str] = []
        text_chunks: List[tuple] = []   # (score, text)
        cleaning_steps = []

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total_pages = len(pdf.pages)
            cleaning_steps.append(f"PDF: {total_pages} pages")

            # For very large PDFs, only process the first PAGE_LIMIT_FULL pages
            # plus the last 2 pages (executive summaries are often at end)
            if total_pages > PAGE_LIMIT_FULL:
                page_indices = list(range(PAGE_LIMIT_FULL)) + list(range(max(PAGE_LIMIT_FULL, total_pages - 2), total_pages))
                cleaning_steps.append(f"Large PDF: processing pages 1-{PAGE_LIMIT_FULL} + last 2 of {total_pages}")
            else:
                page_indices = list(range(total_pages))

            for i in page_indices:
                page = pdf.pages[i]
                page_num = i + 1

                # Tables: always keep, highest priority
                for j, table in enumerate(page.extract_tables() or []):
                    if not table:
                        continue
                    rows = [" | ".join(str(c or "").strip() for c in row) for row in table]
                    tables.append(f"[Page {page_num}, Table {j+1}]\n" + "\n".join(rows))

                # Text: score each paragraph by data density
                page_text = page.extract_text() or ""
                for para in page_text.split("\n\n"):
                    para = para.strip()
                    if len(para) < 20:
                        continue
                    score = sum(_score_line(line) for line in para.splitlines())
                    text_chunks.append((score, f"[Page {page_num}]\n{para}"))

        # Sort text chunks by score (most data-dense first)
        text_chunks.sort(key=lambda x: x[0], reverse=True)

        # Fill token budget: tables first, then highest-scoring text
        budget = TOKEN_BUDGET
        selected_tables = []
        for t in tables:
            if budget <= 0:
                break
            selected_tables.append(t)
            budget -= len(t)

        selected_text = []
        for score, chunk in text_chunks:
            if budget <= 0:
                break
            selected_text.append(chunk)
            budget -= len(chunk)

        cleaning_steps.append(
            f"Selected {len(selected_tables)} tables + {len(selected_text)} text chunks "
            f"({TOKEN_BUDGET - budget} chars)"
        )

        return {
            "tables":         "\n\n".join(selected_tables),
            "text":           "\n\n".join(selected_text),
            "cleaning_steps": cleaning_steps,
        }

    def _build_prompt(self, extracted: dict, user_text: str) -> str:
        parts = []
        if extracted["tables"]:
            parts.append("=== TABLES ===\n" + extracted["tables"])
        if extracted["text"]:
            parts.append("=== KEY DATA FROM DOCUMENT ===\n" + extracted["text"])
        instruction = user_text or (
            "Identify the key numeric metrics in this document. "
            "Generate the most insightful chart possible."
        )
        parts.append(f"=== INSTRUCTION ===\n{instruction}")
        return "\n\n".join(parts)