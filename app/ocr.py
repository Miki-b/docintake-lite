"""OCR for lab-report PDFs on CPU using a Hugging Face model.

Primary engine: python-doctr (pretrained detection+recognition weights pulled
from the HF hub), with pypdfium2 rendering each PDF page to an image.

If doctr cannot be imported or run, we fall back to a small TrOCR model
(microsoft/trocr-small-printed) via transformers, and report which engine ran.

Returns the concatenated text plus per-word confidence where the engine
exposes it (doctr does; TrOCR does not, so confidence is None there).
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field

import numpy as np
import pypdfium2 as pdfium

# Render scale: ~216 DPI. Higher helps recognition on noisy scans.
_RENDER_SCALE = 3.0


@dataclass
class OcrResult:
    text: str
    words: list[dict] = field(default_factory=list)  # {"value": str, "confidence": float|None}
    engine: str = ""
    mean_confidence: float | None = None


def render_pages(pdf_bytes: bytes) -> list[np.ndarray]:
    """Render every page of a PDF to an RGB uint8 numpy array via pypdfium2."""
    pdf = pdfium.PdfDocument(pdf_bytes)
    pages: list[np.ndarray] = []
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=_RENDER_SCALE)
            pil = bitmap.to_pil().convert("RGB")
            pages.append(np.asarray(pil))
    finally:
        pdf.close()
    return pages


@functools.lru_cache(maxsize=1)
def _doctr_model():
    from doctr.models import ocr_predictor

    # pretrained=True downloads weights from the HF hub on first run.
    return ocr_predictor(pretrained=True, assume_straight_pages=True)


def _ocr_doctr(pages: list[np.ndarray]) -> OcrResult:
    model = _doctr_model()
    result = model(pages)
    words: list[dict] = []
    lines_text: list[str] = []
    for page in result.pages:
        for block in page.blocks:
            for line in block.lines:
                line_words = []
                for word in line.words:
                    conf = float(word.confidence)
                    words.append({"value": word.value, "confidence": conf})
                    line_words.append(word.value)
                if line_words:
                    lines_text.append(" ".join(line_words))
    confs = [w["confidence"] for w in words if w["confidence"] is not None]
    mean_conf = float(np.mean(confs)) if confs else None
    return OcrResult(
        text="\n".join(lines_text),
        words=words,
        engine="python-doctr",
        mean_confidence=mean_conf,
    )


def _ocr_trocr(pages: list[np.ndarray]) -> OcrResult:
    # Fallback: small printed-text TrOCR. No per-word confidence exposed.
    from PIL import Image
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel

    name = "microsoft/trocr-small-printed"
    processor = TrOCRProcessor.from_pretrained(name)
    model = VisionEncoderDecoderModel.from_pretrained(name)
    texts = []
    for arr in pages:
        image = Image.fromarray(arr).convert("RGB")
        pixel_values = processor(images=image, return_tensors="pt").pixel_values
        generated = model.generate(pixel_values, max_new_tokens=256)
        texts.append(processor.batch_decode(generated, skip_special_tokens=True)[0])
    return OcrResult(text="\n".join(texts), words=[], engine="trocr-small-printed")


def ocr_pdf(pdf_bytes: bytes) -> OcrResult:
    """OCR a PDF (bytes). Tries doctr first, then TrOCR; reports the engine used."""
    pages = render_pages(pdf_bytes)
    try:
        return _ocr_doctr(pages)
    except Exception as doctr_err:  # noqa: BLE001 - fall back on any doctr failure
        try:
            res = _ocr_trocr(pages)
            res.engine += " (doctr unavailable)"
            return res
        except Exception as trocr_err:  # noqa: BLE001
            raise RuntimeError(
                f"OCR failed. doctr error: {doctr_err!r}; trocr error: {trocr_err!r}"
            ) from trocr_err


if __name__ == "__main__":  # quick manual check
    import sys
    from pathlib import Path

    path = Path(sys.argv[1])
    out = ocr_pdf(path.read_bytes())
    print(f"engine={out.engine} mean_conf={out.mean_confidence}")
    print(out.text)
