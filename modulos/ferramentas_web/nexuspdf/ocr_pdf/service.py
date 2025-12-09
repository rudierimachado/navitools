import os
import tempfile
from typing import List

import requests
from pdf2image import convert_from_path


OCR_SPACE_ENDPOINT = "https://api.ocr.space/parse/image"


def _call_ocr_space_api(image_path: str, page_number: int) -> str:
    """Envia uma imagem para a API OCR.Space e retorna o texto extraído.

    Lê a API key da variável de ambiente ``OCR_SPACE_API_KEY``.
    Em caso de falha controlada, retorna uma mensagem de erro para aquela página,
    sem derrubar o processamento do PDF inteiro.
    """

    api_key = os.getenv("OCR_SPACE_API_KEY")
    if not api_key:
        return (
            f"[Erro ao processar OCR na página {page_number}: "
            "OCR_SPACE_API_KEY não configurada no servidor.]\n"
        )

    try:
        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f)}
            data = {
                # Idioma principal: português. Se quiser inglês também,
                # podemos depois testar "eng" ou outra combinação aceita.
                "language": "por",
                "apikey": api_key,
                "isOverlayRequired": False,
            }

            response = requests.post(OCR_SPACE_ENDPOINT, files=files, data=data, timeout=120)
    except Exception as exc:  # noqa: BLE001
        return f"[Erro ao chamar API de OCR na página {page_number}: {exc}]\n"

    if response.status_code != 200:
        return (
            f"[Erro ao processar OCR na página {page_number}: "
            f"HTTP {response.status_code} da API de OCR.]\n"
        )

    try:
        payload = response.json()
    except ValueError:
        return (
            f"[Erro ao processar OCR na página {page_number}: "
            "Resposta inválida da API de OCR (JSON).]\n"
        )

    if payload.get("IsErroredOnProcessing"):
        message = payload.get("ErrorMessage") or payload.get("ErrorMessageDetails") or "Erro desconhecido"
        if isinstance(message, list):
            message = "; ".join(message)
        return f"[Erro ao processar OCR na página {page_number}: {message}]\n"

    parsed_results = payload.get("ParsedResults") or []
    texts = []
    for result in parsed_results:
        text = result.get("ParsedText") or ""
        if text:
            texts.append(text)

    combined = "\n".join(texts).strip()
    if not combined:
        return (
            f"[Nenhum texto reconhecido na página {page_number} pela API de OCR.]\n"
        )

    return combined + "\n"


def perform_ocr_on_pdf(input_path: str) -> str:
    """Executa OCR em um PDF usando a API externa (OCR.Space).

    - Converte cada página do PDF em imagem usando pdf2image (Poppler).
    - Envia cada página para a API OCR.Space.
    - Concatena o texto de todas as páginas em uma única string.
    """

    if not os.path.exists(input_path):
        raise FileNotFoundError("Arquivo PDF de entrada não encontrado para OCR.")

    try:
        pages = convert_from_path(input_path, dpi=150)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao converter PDF em imagens para OCR: {exc}") from exc

    if not pages:
        return "Nenhuma página foi encontrada no PDF para executar OCR."

    texts: List[str] = []

    max_pages = 50
    pages_to_process = pages[:max_pages]

    for page_number, image in enumerate(pages_to_process, start=1):
        image = image.convert("L")
        max_width = 2000
        if image.width > max_width:
            ratio = max_width / float(image.width)
            new_height = int(image.height * ratio)
            image = image.resize((max_width, new_height))

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=f"_ocr_page_{page_number}.png")
        os.close(tmp_fd)

        try:
            image.save(tmp_path, format="PNG")
        except Exception as exc:  # noqa: BLE001
            header = f"\n\n===== Página {page_number} =====\n"
            texts.append(header + f"[Erro ao salvar imagem temporária da página: {exc}]\n")
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            continue

        try:
            page_text = _call_ocr_space_api(tmp_path, page_number)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        header = f"\n\n===== Página {page_number} =====\n"
        texts.append(header + (page_text or ""))

    combined_text = "".join(texts).strip()

    if not combined_text:
        return "Nenhum texto pôde ser extraído deste PDF usando OCR."

    return combined_text
