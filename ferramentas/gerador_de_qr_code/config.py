import qrcode
from PIL import Image, ImageDraw, ImageFont
import base64
import io
import os
import tempfile
import re
import urllib.parse

class QRConfig:
    # Configurações básicas
    BOX_SIZE = 10
    BORDER = 4
    ERROR_CORRECTION = qrcode.constants.ERROR_CORRECT_H
    
    # Cores padrão
    DEFAULT_FILL_COLOR = '#000000'
    DEFAULT_BACK_COLOR = '#FFFFFF'
    
    # Tamanhos
    SIZES = {
        'small': 200,
        'medium': 400,
        'large': 800
    }

def validate_url(url):
    """Valida e normaliza URL"""
    if not url:
        return False, "URL não pode estar vazia"
    
    # Adiciona http:// se não tiver protocolo
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Validação básica de URL
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    if url_pattern.match(url):
        return True, url
    else:
        return False, "URL inválida"

def validate_wifi_data(ssid, password, security, hidden):
    """Valida dados do WiFi"""
    if not ssid:
        return False, "Nome da rede (SSID) é obrigatório"
    
    if security in ['WPA', 'WEP'] and not password:
        return False, "Senha é obrigatória para redes protegidas"
    
    return True, None

def validate_whatsapp_data(phone, message):
    """Valida dados do WhatsApp"""
    if not phone:
        return False, "Número de telefone é obrigatório"
    
    # Remove caracteres não numéricos
    clean_phone = re.sub(r'[^\d]', '', phone)
    
    # Verifica se tem pelo menos 10 dígitos
    if len(clean_phone) < 10:
        return False, "Número de telefone deve ter pelo menos 10 dígitos"
    
    # Adiciona código do Brasil se necessário
    if len(clean_phone) == 10 or len(clean_phone) == 11:
        clean_phone = '55' + clean_phone
    elif not clean_phone.startswith('55'):
        clean_phone = '55' + clean_phone
    
    return True, clean_phone

def validate_vcard_data(name, phone, email, organization, url):
    """Valida dados do vCard"""
    if not name:
        return False, "Nome é obrigatório"
    
    # Valida email se fornecido
    if email and not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return False, "Email inválido"
    
    return True, None

def format_wifi_data(ssid, password, security, hidden):
    """Formata dados para QR Code WiFi"""
    wifi_string = f"WIFI:T:{security};S:{ssid};"
    
    if password:
        wifi_string += f"P:{password};"
    
    if hidden:
        wifi_string += "H:true;"
    
    wifi_string += ";"
    return wifi_string

def format_whatsapp_data(phone, message):
    """Formata dados para QR Code WhatsApp"""
    encoded_message = urllib.parse.quote(message) if message else ""
    return f"https://wa.me/{phone}?text={encoded_message}"

def format_vcard_data(name, phone, email, organization, url):
    """Formata dados para QR Code vCard"""
    vcard = "BEGIN:VCARD\nVERSION:3.0\n"
    
    # Nome
    vcard += f"FN:{name}\n"
    
    # Telefone
    if phone:
        clean_phone = re.sub(r'[^\d]', '', phone)
        vcard += f"TEL:{clean_phone}\n"
    
    # Email
    if email:
        vcard += f"EMAIL:{email}\n"
    
    # Organização
    if organization:
        vcard += f"ORG:{organization}\n"
    
    # URL
    if url:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        vcard += f"URL:{url}\n"
    
    vcard += "END:VCARD"
    return vcard

def generate_qr_code(data, fill_color=None, back_color=None, size='medium'):
    """Gera QR Code com os dados fornecidos"""
    try:
        # Configuração do QR Code
        qr = qrcode.QRCode(
            version=1,
            error_correction=QRConfig.ERROR_CORRECTION,
            box_size=QRConfig.BOX_SIZE,
            border=QRConfig.BORDER,
        )
        
        qr.add_data(data)
        qr.make(fit=True)
        
        # Cores
        fill = fill_color or QRConfig.DEFAULT_FILL_COLOR
        back = back_color or QRConfig.DEFAULT_BACK_COLOR
        
        # Cria a imagem
        img = qr.make_image(fill_color=fill, back_color=back)
        
        # Redimensiona se necessário
        target_size = QRConfig.SIZES.get(size, QRConfig.SIZES['medium'])
        if img.size[0] != target_size:
            img = img.resize((target_size, target_size), Image.Resampling.LANCZOS)
        
        return img, None
        
    except Exception as e:
        return None, f"Erro ao gerar QR Code: {str(e)}"

def save_qr_temp(img, filename):
    """Salva QR Code temporariamente"""
    try:
        temp_dir = tempfile.gettempdir()
        qr_temp_dir = os.path.join(temp_dir, 'qr_codes')
        
        if not os.path.exists(qr_temp_dir):
            os.makedirs(qr_temp_dir)
        
        file_path = os.path.join(qr_temp_dir, filename)
        img.save(file_path, 'PNG')
        
        return file_path
        
    except Exception as e:
        raise Exception(f"Erro ao salvar QR Code: {str(e)}")

def qr_to_base64(img):
    """Converte QR Code para base64"""
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"