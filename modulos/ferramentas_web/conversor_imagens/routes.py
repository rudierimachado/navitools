from flask import Blueprint, render_template, request, jsonify, send_file, session
import os
import tempfile
from werkzeug.utils import secure_filename
from .config import Config, allowed_file, convert_image, create_zip_download, get_image_info

conversor_bp = Blueprint('conversor', __name__, 
                        template_folder='templates',
                        static_folder='static')

@conversor_bp.route('/')
def conversor_home():
    # Carregar configuração do módulo conversor
    conversor_version = '2.0.0'  # Versão fixa
    
    return render_template('conversor_imagens.html', 
                         module_name='Conversor de Imagens',
                         module_version=conversor_version,
                         output_formats=Config.OUTPUT_FORMATS)

@conversor_bp.route('/upload', methods=['POST'])
def upload_files():
    try:
        if 'files[]' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        
        files = request.files.getlist('files[]')
        output_format = request.form.get('format', 'png')
        quality = int(request.form.get('quality', 85))
        target_size_kb = request.form.get('target_size_kb', None)
        web_optimize = request.form.get('web_optimize', 'false') == 'true'
        
        if target_size_kb:
            target_size_kb = int(target_size_kb)
        
        if not files or files[0].filename == '':
            return jsonify({'error': 'Nenhum arquivo selecionado'}), 400
        
        converted_files = []
        errors = []
        
        for file in files:
            if file and allowed_file(file.filename):
                # Salvar arquivo temporariamente
                filename = secure_filename(file.filename)
                temp_path = os.path.join(tempfile.gettempdir(), filename)
                file.save(temp_path)
                
                try:
                    # Obter info da imagem original
                    original_info = get_image_info(temp_path)
                    
                    # Converter imagem
                    converted_path, converted_filename = convert_image(
                        temp_path, output_format, quality, target_size_kb, web_optimize
                    )
                    
                    # Obter info da imagem convertida
                    converted_info = get_image_info(converted_path)
                    
                    # Calcular economia de espaço
                    compression_ratio = 0
                    if original_info and converted_info:
                        original_size = original_info['file_size']
                        converted_size = converted_info['file_size']
                        if original_size > 0:
                            compression_ratio = round((1 - (converted_size / original_size)) * 100, 1)
                    
                    converted_files.append({
                        'original_name': file.filename,
                        'converted_name': converted_filename,
                        'converted_path': converted_path,
                        'original_size': original_info['file_size'] if original_info else 0,
                        'converted_size': converted_info['file_size'] if converted_info else 0,
                        'compression_ratio': compression_ratio,
                        'original_dimensions': f"{original_info['width']}x{original_info['height']}" if original_info else "N/A",
                        'converted_dimensions': f"{converted_info['width']}x{converted_info['height']}" if converted_info else "N/A",
                        'original_format': original_info['format'] if original_info else "N/A"
                    })
                    
                    # Limpar arquivo temporário original
                    os.unlink(temp_path)
                    
                except Exception as e:
                    errors.append(f"Erro ao converter {file.filename}: {str(e)}")
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
            else:
                errors.append(f"Formato não suportado: {file.filename}")
        
        # Salvar lista de arquivos na sessão para download
        session['converted_files'] = [(f['converted_path'], f['converted_name']) for f in converted_files]
        
        return jsonify({
            'success': True,
            'files': converted_files,
            'errors': errors,
            'total_converted': len(converted_files),
            'total_space_saved': sum([f['original_size'] - f['converted_size'] for f in converted_files if f['compression_ratio'] > 0])
        })
        
    except Exception as e:
        return jsonify({'error': f"Erro interno: {str(e)}"}), 500

@conversor_bp.route('/download-all')
def download_all():
    try:
        converted_files = session.get('converted_files', [])
        
        if not converted_files:
            return jsonify({'error': 'Nenhum arquivo para download'}), 400
        
        # Criar ZIP com todos os arquivos
        zip_path = create_zip_download(converted_files)
        
        # Enviar arquivo e limpar depois
        return send_file(
            zip_path,
            as_attachment=True,
            download_name='imagens_convertidas.zip',
            mimetype='application/zip'
        )
        
    except Exception as e:
        return jsonify({'error': f"Erro ao criar download: {str(e)}"}), 500

@conversor_bp.route('/download/<path:filename>')
def download_single(filename):
    try:
        # Buscar arquivo na lista da sessão
        converted_files = session.get('converted_files', [])
        file_path = None
        
        for path, name in converted_files:
            if name == filename:
                file_path = path
                break
        
        if not file_path or not os.path.exists(file_path):
            return jsonify({'error': 'Arquivo não encontrado'}), 404
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        return jsonify({'error': f"Erro ao fazer download: {str(e)}"}), 500