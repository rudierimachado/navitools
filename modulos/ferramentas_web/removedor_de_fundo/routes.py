import os
import json
import zipfile
from flask import Blueprint, render_template, request, jsonify, send_file, current_app
from werkzeug.utils import secure_filename
from pathlib import Path
import tempfile
from threading import Thread
import uuid

from .config import Config, allowed_file, get_unique_filename
from .image_processor import BackgroundRemover, BatchProcessor

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

@removedor_de_fundo_bp.route('/')
def index():
    """Página principal do Removedor De Fundo"""
    return render_template('removedor_de_fundo.html')

@removedor_de_fundo_bp.route('/upload', methods=['POST'])
def upload_image():
    """Upload de imagem única"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Nenhum arquivo selecionado'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Formato de arquivo não suportado'}), 400
        
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
        return jsonify({'error': f'Erro no upload: {str(e)}'}), 500

@removedor_de_fundo_bp.route('/process', methods=['POST'])
def process_image():
    """Processa imagem removendo o fundo"""
    try:
        data = request.json
        filename = data.get('filename')
        model = data.get('model', 'u2net')
        bg_type = data.get('bg_type', 'transparent')
        custom_color = data.get('custom_color')
        
        if not filename:
            return jsonify({'error': 'Nome do arquivo não informado'}), 400
        
        input_path = Config.UPLOAD_DIR / filename
        if not input_path.exists():
            return jsonify({'error': 'Arquivo não encontrado'}), 404
        
        # Processa imagem
        remover = BackgroundRemover(model)
        processed_image = remover.remove_background(input_path)
        
        # Converte cor customizada se fornecida
        if custom_color and bg_type == 'custom':
            custom_color = tuple(int(custom_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
        
        # Aplica novo fundo
        final_image = remover.apply_background(processed_image, bg_type, custom_color)
        
        # Melhora bordas
        final_image = remover.enhance_edges(final_image)
        
        # Salva resultado
        output_filename = f"processed_{filename}"
        output_path = Config.PROCESSED_DIR / output_filename
        
        if bg_type == 'transparent':
            final_image.save(output_path, 'PNG')
        else:
            final_image = final_image.convert('RGB')
            final_image.save(output_path, 'JPEG', quality=95)
        
        return jsonify({
            'success': True,
            'output_filename': output_filename,
            'preview_url': f'/removedor-de-fundo/preview/{output_filename}'
        })
        
    except Exception as e:
        return jsonify({'error': f'Erro no processamento: {str(e)}'}), 500

@removedor_de_fundo_bp.route('/batch-upload', methods=['POST'])
def batch_upload():
    """Upload de múltiplas imagens"""
    try:
        if 'files[]' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        
        files = request.files.getlist('files[]')
        uploaded_files = []
        
        for file in files:
            if file.filename and allowed_file(file.filename):
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
        return jsonify({'error': f'Erro no upload: {str(e)}'}), 500

@removedor_de_fundo_bp.route('/batch-process', methods=['POST'])
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
        return jsonify({'error': f'Erro no processamento: {str(e)}'}), 500

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
        return jsonify({'error': f'Erro no download: {str(e)}'}), 500

@removedor_de_fundo_bp.route('/preview/<filename>')
def preview_image(filename):
    """Visualiza imagem processada"""
    try:
        file_path = Config.PROCESSED_DIR / filename
        if not file_path.exists():
            return jsonify({'error': 'Arquivo não encontrado'}), 404
        
        return send_file(file_path)
        
    except Exception as e:
        return jsonify({'error': f'Erro ao carregar imagem: {str(e)}'}), 500

@removedor_de_fundo_bp.route('/download/<filename>')
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
        return jsonify({'error': f'Erro no download: {str(e)}'}), 500

@removedor_de_fundo_bp.route('/models')
def get_models():
    """Retorna modelos disponíveis"""
    return jsonify({
        'models': Config.AI_MODELS,
        'output_formats': Config.OUTPUT_FORMATS
    })

@removedor_de_fundo_bp.route('/cleanup', methods=['POST'])
def cleanup_files():
    """Limpa arquivos antigos"""
    try:
        import time
        import shutil
        
        current_time = time.time()
        max_age = 24 * 60 * 60  # 24 horas
        
        # Limpa uploads antigos
        for file_path in Config.UPLOAD_DIR.glob('*'):
            if current_time - file_path.stat().st_mtime > max_age:
                file_path.unlink()
        
        # Limpa processados antigos
        for file_path in Config.PROCESSED_DIR.glob('*'):
            if file_path.is_file() and current_time - file_path.stat().st_mtime > max_age:
                file_path.unlink()
            elif file_path.is_dir() and current_time - file_path.stat().st_mtime > max_age:
                shutil.rmtree(file_path)
        
        return jsonify({'success': True, 'message': 'Limpeza realizada'})
        
    except Exception as e:
        return jsonify({'error': f'Erro na limpeza: {str(e)}'}), 500