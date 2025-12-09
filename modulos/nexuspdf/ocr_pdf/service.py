import os
from typing import List

from pdf2image import convert_from_path
import pytesseract


def perform_ocr_on_pdf(input_path: str) -> str:
    """Executa OCR em um PDF e retorna o texto extraído como string.

    - Converte cada página do PDF em imagem usando pdf2image (Poppler).
    - Aplica Tesseract OCR em cada imagem.
    - Concatena o texto de todas as páginas em uma única string.
    """

    if not os.path.exists(input_path):
        raise FileNotFoundError("Arquivo PDF de entrada não encontrado para OCR.")

    # Converter PDF em imagens (uma por página)
    try:
        pages = convert_from_path(input_path)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao converter PDF em imagens para OCR: {exc}") from exc

    if not pages:
        return "Nenhuma página foi encontrada no PDF para executar OCR."

    texts: List[str] = []

    for page_number, image in enumerate(pages, start=1):
        try:
            page_text = pytesseract.image_to_string(image, lang="por+eng")
        except Exception as exc:  # noqa: BLE001
            page_text = f"[Erro ao processar OCR na página {page_number}: {exc}]\n"

        header = f"\n\n===== Página {page_number} =====\n"
        texts.append(header + (page_text or ""))

    combined_text = "".join(texts).strip()

    if not combined_text:
        return "Nenhum texto pôde ser extraído deste PDF usando OCR."

    return combined_text
