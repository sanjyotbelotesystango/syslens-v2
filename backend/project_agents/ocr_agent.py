"""
project_agents/ocr_agent.py — OCR-based text extraction from images.

Resume requirement:
  "images (OCR-based extraction)"

When to use vs vision_agent:
  - vision_agent: image IS a chart → LLM Vision recreates the chart visually
  - ocr_agent:    image contains TEXT data (scanned tables, invoices, reports)
               → Tesseract extracts text → AnalystAgent builds chart

The router decides which to use based on user intent.
"""

from __future__ import annotations
import io

from ..models import AgentMode, SessionContext, AnalysisResult
from ..project_agents.analyst_agent import AnalystAgent


class OcrAgent:
    """
    Extracts text from an image via Tesseract OCR,
    then passes the text to AnalystAgent for visualization.
    """

    def __init__(self):
        self._analyst = AnalystAgent()

    def run(
        self,
        image_bytes: bytes,
        user_text: str,
        ctx: SessionContext,
    ) -> AnalysisResult:
        """
        Args:
            image_bytes: Raw image file bytes (PNG, JPG, etc.)
            user_text:   Optional user instruction.
            ctx:         Session context.

        Returns:
            AnalysisResult with chart from OCR-extracted text.
        """
        ocr_text  = self._extract_text(image_bytes)
        prompt    = self._build_prompt(ocr_text, user_text)
        result    = self._analyst.run(prompt, ctx)
        result.mode           = AgentMode.OCR_IMAGE.value
        result.cleaning_steps = [f"OCR extracted {len(ocr_text)} characters"] + result.cleaning_steps
        return result

    def _extract_text(self, image_bytes: bytes) -> str:
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            raise ImportError(
                "pytesseract and Pillow are required for OCR. "
                "Run: pip install pytesseract Pillow\n"
                "Also install Tesseract: https://github.com/tesseract-ocr/tesseract"
            )

        image  = Image.open(io.BytesIO(image_bytes))
        # Use page segmentation mode 6 (assume a single block of text)
        config = "--psm 6"
        text   = pytesseract.image_to_string(image, config=config)
        return text.strip()

    def _build_prompt(self, ocr_text: str, user_text: str) -> str:
        instruction = user_text or (
            "Extract all numeric data from the following text and "
            "create the most appropriate visualization."
        )
        return (
            f"=== OCR EXTRACTED TEXT FROM IMAGE ===\n{ocr_text[:5000]}\n\n"
            f"=== INSTRUCTION ===\n{instruction}"
        )