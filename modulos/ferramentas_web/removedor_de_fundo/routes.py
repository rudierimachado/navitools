import os
import json
import zipfile
import logging
from flask import Blueprint, render_template, request, jsonify, send_file

from werkzeug.utils import secure_filename
from pathlib import Path
import tempfile
from threading import Thread
import uuid
from PIL import Image, UnidentifiedImageError

from .config import Config, allowed_file, get_unique_filename
from .image_processor import BackgroundRemover, BatchProcessor

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Inicializar diretórios
Config.create_directories()

removedor_de_fundo_bp = Blueprint(
    'removedor_de_fundo', 
    __name__, 
    url_prefix='/removedor-de-fundo', 
    template_folder='templates',
    static_folder='static'
)

# Armazenamento de sessões de processamento
processing_sessions = {}
logger = logging.getLogger(__name__)

MAX_BATCH_FILES = Config.MAX_FILES_PER_BATCH

limiter = Limiter(key_func=get_remote_address)
limiter.limit(f"{Config.MAX_REQUESTS_PER_IP}/hour")(removedor_de_fundo_bp)


def _validate_image_upload(file):
    if not file or file.filename == '':
        return False, 'Nenhum arquivo selecionado'
    if not allowed_file(file.filename):
        return False, 'Formato de arquivo não suportado'

    # Garantir tamanho máximo
    file.stream.seek(0, os.SEEK_END)
    file_size = file.stream.tell()
    file.stream.seek(0)
    if file_size > Config.MAX_CONTENT_LENGTH:
        return False, 'Arquivo excede o limite de 16MB'

    # Validar assinatura real da imagem
    try:
        Image.open(file.stream).verify()
    except (UnidentifiedImageError, OSError):
        file.stream.seek(0)
        return False, 'Arquivo de imagem inválido'

    file.stream.seek(0)
    return True, None


@removedor_de_fundo_bp.route('/')
def index():
    """Página principal do Removedor De Fundo"""
    return render_template('removedor_de_fundo.html')


@removedor_de_fundo_bp.route('/upload', methods=['POST'])
@limiter.limit("10/minute")
def upload_image():
    """Upload de imagem única"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        
        file = request.files['file']
        is_valid, error_message = _validate_image_upload(file)
        if not is_valid:
            return jsonify({'error': error_message}), 400
        
        # Salva arquivo
        filename = get_unique_filename(file.filename)
        filepath = Config.UPLOAD_DIR / filename
        file.save(filepath)
        
        return jsonify({
            'success': True,
            'filename': filename,
            'original_name': file.filename
        })
        
    except Exception as e:
        logger.exception("Erro no upload de imagem única")
        return jsonify({'error': 'Erro interno no upload'}), 500


# Na função process_image, substitua por:
@removedor_de_fundo_bp.route('/process', methods=['POST'])
@limiter.limit("10/minute")
def process_image():
    """Processa imagem com rembg super otimizado"""
    try:
        data = request.json
        filename = data.get('filename')
        model = data.get('model', 'isnet-general-use')
        quality = data.get('quality', 'media')
        
        bg_type = data.get('bg_type', 'transparent')
        custom_color = data.get('custom_color')
        
        if not filename:
            return jsonify({'error': 'Nome do arquivo não informado'}), 400
        
        input_path = Config.UPLOAD_DIR / filename
        if not input_path.exists():
            return jsonify({'error': 'Arquivo não encontrado'}), 404
        
        logger.info(f"Processando {filename} com {model} em qualidade {quality}")
        
        # Usar processador super otimizado
        from .image_processor import SuperRembgProcessor
        processor = SuperRembgProcessor(model)
        
        # Remover fundo com qualidade ultra
        processed_image = processor.remove_background(input_path, quality)
        
        # Aplicar fundo se necessário
        if custom_color and bg_type == 'custom':
            custom_color = tuple(int(custom_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
        
        final_image = processor.apply_background(processed_image, bg_type, custom_color)
        
        # Salvar resultado
        output_filename = f"processed_{filename.rsplit('.', 1)[0]}.png"
        output_path = Config.PROCESSED_DIR / output_filename
        
        # Sempre PNG para preservar qualidade
        final_image.save(output_path, 'PNG', optimize=True, compress_level=6)
        
        file_size = output_path.stat().st_size
        
        logger.info(f"Processamento concluído: {output_path} ({file_size} bytes)")
        
        return jsonify({
            'success': True,
            'output_filename': output_filename,
            'preview_url': f'/removedor-de-fundo/preview/{output_filename}',
            'model_used': model,
            'quality_used': quality,
            'file_size': file_size,
            'message': 'Fundo removido com sucesso!'
        })
        
    except Exception as e:
        logger.exception("Erro ao processar imagem")
        return jsonify({'error': f'Erro no processamento: {str(e)}'}), 500

@removedor_de_fundo_bp.route('/batch-upload', methods=['POST'])
@limiter.limit("6/minute")
def batch_upload():
    """Upload de múltiplas imagens"""
    try:
        if 'files[]' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        
        files = request.files.getlist('files[]')
        if not files:
            return jsonify({'error': 'Nenhum arquivo selecionado'}), 400
        if len(files) > MAX_BATCH_FILES:
            return jsonify({'error': f'Limite de {MAX_BATCH_FILES} arquivos excedido'}), 400

        uploaded_files = []
        
        for file in files:
            is_valid, error_message = _validate_image_upload(file)
            if not is_valid:
                continue

            filename = get_unique_filename(file.filename)
            filepath = Config.UPLOAD_DIR / filename
            file.save(filepath)
            
            uploaded_files.append({
                'filename': filename,
                'original_name': file.filename
            })

        return jsonify({
            'success': True,
            'files': uploaded_files,
            'count': len(uploaded_files)
        })
        
    except Exception as e:
        logger.exception("Erro no upload em lote")
        return jsonify({'error': 'Erro interno no upload'}), 500


@removedor_de_fundo_bp.route('/batch-process', methods=['POST'])
@limiter.limit("4/minute")
def batch_process():
    """Processa múltiplas imagens em lote"""
    try:
        data = request.json
        filenames = data.get('filenames', [])
        model = data.get('model', 'u2net')
        bg_type = data.get('bg_type', 'transparent')
        custom_color = data.get('custom_color')
        
        if not filenames:
            return jsonify({'error': 'Nenhum arquivo para processar'}), 400
        if len(filenames) > MAX_BATCH_FILES:
            return jsonify({'error': f'Processamento limitado a {MAX_BATCH_FILES} arquivos por vez'}), 400
        
        # Gera ID único para a sessão
        session_id = str(uuid.uuid4())
        
        # Converte cor customizada se fornecida
        if custom_color and bg_type == 'custom':
            custom_color = tuple(int(custom_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
        
        # Cria diretório para a sessão
        session_dir = Config.PROCESSED_DIR / session_id
        session_dir.mkdir(exist_ok=True)
        
        # Prepara caminhos dos arquivos
        input_paths = [Config.UPLOAD_DIR / filename for filename in filenames]
        
        # Inicializa processamento em lote
        processor = BatchProcessor(model)
        
        # Armazena informações da sessão
        processing_sessions[session_id] = {
            'total': len(filenames),
            'processed': 0,
            'status': 'processing',
            'results': []
        }
        
        def process_batch_async():
            try:
                def progress_callback(current, total):
                    processing_sessions[session_id]['processed'] = current
                
                processor.set_progress_callback(progress_callback)
                results = processor.process_batch(input_paths, session_dir, bg_type, custom_color)
                
                processing_sessions[session_id]['results'] = results
                processing_sessions[session_id]['status'] = 'completed'
                
            except Exception as e:
                processing_sessions[session_id]['status'] = 'error'
                processing_sessions[session_id]['error'] = str(e)
        
        # Inicia processamento em thread separada
        thread = Thread(target=process_batch_async)
        thread.start()
        
        return jsonify({
            'success': True,
            'session_id': session_id
        })
        
    except Exception as e:
        logger.exception("Erro ao processar em lote")
        return jsonify({'error': 'Erro interno no processamento'}), 500


@removedor_de_fundo_bp.route('/batch-status/<session_id>')
def batch_status(session_id):
    """Verifica status do processamento em lote"""
    if session_id not in processing_sessions:
        return jsonify({'error': 'Sessão não encontrada'}), 404
    
    session = processing_sessions[session_id]
    return jsonify({
        'status': session['status'],
        'total': session['total'],
        'processed': session['processed'],
        'progress': (session['processed'] / session['total']) * 100,
        'results': session.get('results', []),
        'error': session.get('error')
    })


@removedor_de_fundo_bp.route('/download-batch/<session_id>')
@limiter.limit("8/minute")
def download_batch(session_id):
    """Download do lote processado em ZIP"""
    try:
        if session_id not in processing_sessions:
            return jsonify({'error': 'Sessão não encontrada'}), 404
        
        session = processing_sessions[session_id]
        if session['status'] != 'completed':
            return jsonify({'error': 'Processamento ainda não finalizado'}), 400
        
        session_dir = Config.PROCESSED_DIR / session_id
        
        # Cria arquivo ZIP temporário
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        
        with zipfile.ZipFile(temp_zip.name, 'w') as zip_file:
            for result in session['results']:
                if result['success']:
                    file_path = Path(result['output_path'])
                    if file_path.exists():
                        zip_file.write(file_path, file_path.name)
        
        return send_file(
            temp_zip.name,
            as_attachment=True,
            download_name=f'processed_images_{session_id}.zip',
            mimetype='application/zip'
        )
        
    except Exception as e:
        logger.exception("Erro ao gerar download em lote")
        return jsonify({'error': 'Erro interno no download'}), 500


@removedor_de_fundo_bp.route('/preview/<filename>')
@limiter.limit("20/minute")
def preview_image(filename):
    """Visualiza imagem processada"""
    try:
        file_path = Config.PROCESSED_DIR / filename
        if not file_path.exists():
            return jsonify({'error': 'Arquivo não encontrado'}), 404
        
        return send_file(file_path)
        
    except Exception as e:
        logger.exception("Erro ao carregar preview")
        return jsonify({'error': 'Erro interno ao carregar imagem'}), 500


@removedor_de_fundo_bp.route('/download/<filename>')
@limiter.limit("20/minute")
def download_image(filename):
    """Download da imagem processada"""
    try:
        file_path = Config.PROCESSED_DIR / filename
        if not file_path.exists():
            return jsonify({'error': 'Arquivo não encontrado'}), 404
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.exception("Erro ao baixar imagem")
        return jsonify({'error': 'Erro interno no download'}), 500


@removedor_de_fundo_bp.route('/models')
def get_models():
    """Retorna modelos disponíveis"""
    return jsonify({
        'models': Config.AI_MODELS,
        'output_formats': Config.OUTPUT_FORMATS
    })


def _cleanup_fs():
    import time
    import shutil
    current_time = time.time()
    max_age = Config.MAX_LIFETIME_SECONDS
    removed = 0

    for file_path in Config.UPLOAD_DIR.glob('*'):
        if current_time - file_path.stat().st_mtime > max_age:
            file_path.unlink(missing_ok=True)
            removed += 1

    for file_path in Config.PROCESSED_DIR.glob('*'):
        if file_path.is_file() and current_time - file_path.stat().st_mtime > max_age:
            file_path.unlink(missing_ok=True)
            removed += 1
        elif file_path.is_dir() and current_time - file_path.stat().st_mtime > max_age:
            shutil.rmtree(file_path, ignore_errors=True)
            removed += 1
    return removed


@removedor_de_fundo_bp.route('/cleanup', methods=['POST'])
@limiter.limit("2/minute")
def cleanup_files():
    """Limpa arquivos antigos"""
    try:
        removed = _cleanup_fs()
        return jsonify({'success': True, 'message': f'Limpeza realizada ({removed} itens).'})
        
    except Exception as e:
        logger.exception("Erro ao limpar arquivos")
        return jsonify({'error': 'Erro interno na limpeza'}), 500