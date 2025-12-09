from flask import Blueprint, render_template, request, jsonify, send_file, session
import os
import tempfile
import uuid
from datetime import datetime
from .config import (
    validate_url, validate_wifi_data, validate_whatsapp_data, validate_vcard_data,
    format_wifi_data, format_whatsapp_data, format_vcard_data,
    generate_qr_code, save_qr_temp, qr_to_base64
)

gerador_de_qr_code_bp = Blueprint('gerador_de_qr_code', __name__, 
                                  template_folder='templates',
                                  static_folder='static')

@gerador_de_qr_code_bp.route('/')
def gerador_home():
    """Página principal do gerador de QR Code"""
    # Carregar configuração do módulo
    import json
    
    gerador_version = '1.0.0'  # Versão fixa
    
    return render_template('gerador_de_qr_code.html',
                         module_name='Gerador de QR Code',
                         module_version=gerador_version)

@gerador_de_qr_code_bp.route('/generate', methods=['POST'])
def generate_qr():
    """Gera QR Code baseado no tipo selecionado"""
    try:
        data = request.get_json()
        qr_type = data.get('type')
        qr_data = data.get('data', {})
        
        # Configurações visuais
        fill_color = data.get('fillColor', '#000000')
        back_color = data.get('backColor', '#FFFFFF')
        size = data.get('size', 'medium')
        
        # Validar e formatar dados baseado no tipo
        if qr_type == 'url':
            is_valid, result = validate_url(qr_data.get('url', ''))
            if not is_valid:
                return jsonify({'success': False, 'error': result}), 400
            qr_content = result
            
        elif qr_type == 'wifi':
            ssid = qr_data.get('ssid', '')
            password = qr_data.get('password', '')
            security = qr_data.get('security', 'WPA')
            hidden = qr_data.get('hidden', False)
            
            is_valid, error = validate_wifi_data(ssid, password, security, hidden)
            if not is_valid:
                return jsonify({'success': False, 'error': error}), 400
            
            qr_content = format_wifi_data(ssid, password, security, hidden)
            
        elif qr_type == 'text':
            text = qr_data.get('text', '')
            if not text:
                return jsonify({'success': False, 'error': 'Texto não pode estar vazio'}), 400
            qr_content = text
            
        elif qr_type == 'whatsapp':
            phone = qr_data.get('phone', '')
            message = qr_data.get('message', '')
            
            is_valid, result = validate_whatsapp_data(phone, message)
            if not is_valid:
                return jsonify({'success': False, 'error': result}), 400
            
            qr_content = format_whatsapp_data(result, message)
            
        elif qr_type == 'vcard':
            name = qr_data.get('name', '')
            phone = qr_data.get('phone', '')
            email = qr_data.get('email', '')
            organization = qr_data.get('organization', '')
            url = qr_data.get('url', '')
            
            is_valid, error = validate_vcard_data(name, phone, email, organization, url)
            if not is_valid:
                return jsonify({'success': False, 'error': error}), 400
            
            qr_content = format_vcard_data(name, phone, email, organization, url)
            
        else:
            return jsonify({'success': False, 'error': 'Tipo de QR Code inválido'}), 400
        
        # Gerar QR Code
        img, error = generate_qr_code(qr_content, fill_color, back_color, size)
        if error:
            return jsonify({'success': False, 'error': error}), 500
        
        # Converter para base64 para preview
        qr_base64 = qr_to_base64(img)
        
        # Salvar temporariamente para download
        filename = f"qr_{uuid.uuid4().hex}.png"
        file_path = save_qr_temp(img, filename)
        
        # Salvar na sessão para download posterior
        if 'qr_files' not in session:
            session['qr_files'] = []
        
        session['qr_files'].append({
            'filename': filename,
            'path': file_path,
            'type': qr_type,
            'created_at': datetime.now().isoformat()
        })
        
        return jsonify({
            'success': True,
            'qr_image': qr_base64,
            'filename': filename,
            'type': qr_type,
            'preview_data': {
                'type': qr_type,
                'content': qr_content[:100] + '...' if len(qr_content) > 100 else qr_content
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Erro interno: {str(e)}'}), 500

@gerador_de_qr_code_bp.route('/download/<filename>')
def download_qr(filename):
    """Download de QR Code individual"""
    try:
        # Buscar arquivo na sessão
        qr_files = session.get('qr_files', [])
        file_info = None
        
        for qr_file in qr_files:
            if qr_file['filename'] == filename:
                file_info = qr_file
                break
        
        if not file_info or not os.path.exists(file_info['path']):
            return jsonify({'error': 'Arquivo não encontrado'}), 404
        
        return send_file(
            file_info['path'],
            as_attachment=True,
            download_name=filename,
            mimetype='image/png'
        )
        
    except Exception as e:
        return jsonify({'error': f'Erro ao fazer download: {str(e)}'}), 500

@gerador_de_qr_code_bp.route('/preview', methods=['POST'])
def preview_qr():
    """Gera preview do QR Code em tempo real"""
    try:
        data = request.get_json()
        qr_type = data.get('type')
        qr_data = data.get('data', {})
        
        # Validação rápida sem gerar o QR Code completo
        if qr_type == 'url':
            url = qr_data.get('url', '')
            if not url:
                return jsonify({'valid': False, 'message': 'Digite uma URL'})
            
            is_valid, result = validate_url(url)
            return jsonify({
                'valid': is_valid,
                'message': 'URL válida' if is_valid else result,
                'preview': result if is_valid else None
            })
            
        elif qr_type == 'wifi':
            ssid = qr_data.get('ssid', '')
            if not ssid:
                return jsonify({'valid': False, 'message': 'Digite o nome da rede'})
            
            return jsonify({
                'valid': True,
                'message': f'WiFi: {ssid}',
                'preview': f'Rede: {ssid}'
            })
            
        elif qr_type == 'text':
            text = qr_data.get('text', '')
            if not text:
                return jsonify({'valid': False, 'message': 'Digite um texto'})
            
            return jsonify({
                'valid': True,
                'message': f'Texto: {len(text)} caracteres',
                'preview': text[:50] + '...' if len(text) > 50 else text
            })
            
        elif qr_type == 'whatsapp':
            phone = qr_data.get('phone', '')
            if not phone:
                return jsonify({'valid': False, 'message': 'Digite um número'})
            
            is_valid, result = validate_whatsapp_data(phone, '')
            return jsonify({
                'valid': is_valid,
                'message': f'WhatsApp: {result}' if is_valid else result,
                'preview': f'WhatsApp: {result}' if is_valid else None
            })
            
        elif qr_type == 'vcard':
            name = qr_data.get('name', '')
            if not name:
                return jsonify({'valid': False, 'message': 'Digite um nome'})
            
            return jsonify({
                'valid': True,
                'message': f'Contato: {name}',
                'preview': f'vCard: {name}'
            })
        
        return jsonify({'valid': False, 'message': 'Tipo inválido'})
        
    except Exception as e:
        return jsonify({'valid': False, 'message': f'Erro: {str(e)}'})