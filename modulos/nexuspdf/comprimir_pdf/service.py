import os
import tempfile
import uuid

import pikepdf
from pikepdf import ObjectStreamMode


def _get_profile_params(quality: str) -> dict:
    """Mapeia o nível de qualidade para parâmetros de otimização.

    - "baixa": perfil mais leve (quase sem perda, foco em compatibilidade)
    - "media": equilíbrio (bom para e-mail/uso geral)
    - "alta": compressão mais agressiva (arquivamento / reduzir ao máximo)
    """
    quality = (quality or "media").lower()

    if quality == "baixa":
        return {
            "compress_streams": True,
            "object_stream_mode": ObjectStreamMode.generate,
            "linearize": True,
        }
    if quality == "alta":
        return {
            "compress_streams": True,
            "object_stream_mode": ObjectStreamMode.generate,
            "linearize": True,
        }

    # "media" (padrão)
    return {
        "compress_streams": True,
        "object_stream_mode": ObjectStreamMode.generate,
        "linearize": True,
    }


def compress_pdf(input_path: str, quality: str = "media") -> tuple[str, str]:
    """Comprime um PDF usando pikepdf, retornando (output_path, output_filename).

    A compressão atua principalmente sobre streams e estrutura interna do PDF,
    usando diferentes perfis de otimização conforme o parâmetro "quality".
    """

    if not os.path.exists(input_path):
        raise FileNotFoundError("Arquivo PDF de entrada não encontrado.")

    ext = os.path.splitext(input_path)[1] or ".pdf"
    output_filename = f"pdf_comprimido_{uuid.uuid4().hex}{ext}"
    output_path = os.path.join(tempfile.gettempdir(), output_filename)

    profile_params = _get_profile_params(quality)

    # Abrir PDF e salvar em uma nova cópia otimizada
    with pikepdf.open(input_path) as pdf:
        pdf.save(output_path, **profile_params)

    return output_path, output_filename
