"""
Módulo de detecção de dispositivos para Flask
Detecta automaticamente dispositivos móveis e tablets para adaptar layouts
"""

import re
from flask import request, g

class DeviceDetector:
    """Classe para detectar tipo de dispositivo baseado no User-Agent"""

    # Padrões regex para detectar dispositivos móveis
    MOBILE_PATTERNS = [
        r'Android.*Mobile',
        r'iPhone',
        r'iPod',
        r'BlackBerry',
        r'BB10',
        r'Windows Phone',
        r'webOS',
        r'Symbian',
        r'Opera Mini',
        r'Mobile',
        r'Phone'
    ]

    # Padrões para tablets (excluindo tablets que também são móveis)
    TABLET_PATTERNS = [
        r'iPad',
        r'Android.*Tablet',
        r'Windows.*Tablet',
        r'Kindle Fire',
        r'Samsung.*Tablet',
        r'Lenovo.*Tablet'
    ]

    # Padrões para dispositivos móveis grandes (phablets)
    PHABLET_PATTERNS = [
        r'Android.*Mobile.*(?:720|1080|1440)x(?:1280|1920|2560)',
        r'iPhone.*(?:6|7|8|X|11|12|13|14|15).*Plus',
        r'iPhone.*(?:6|7|8|X|11|12|13|14|15).*Pro.*Max'
    ]

    @staticmethod
    def get_device_type(user_agent):
        """Retorna o tipo de dispositivo baseado no User-Agent"""
        if not user_agent:
            return 'desktop'

        user_agent = user_agent.upper()

        # Verificar tablets primeiro (para não confundir com móveis)
        for pattern in DeviceDetector.TABLET_PATTERNS:
            if re.search(pattern.upper(), user_agent):
                return 'tablet'

        # Verificar se é phablet (móvel grande)
        for pattern in DeviceDetector.PHABLET_PATTERNS:
            if re.search(pattern.upper(), user_agent):
                return 'phablet'

        # Verificar dispositivos móveis
        for pattern in DeviceDetector.MOBILE_PATTERNS:
            if re.search(pattern.upper(), user_agent):
                return 'mobile'

        return 'desktop'

    @staticmethod
    def is_mobile(user_agent):
        """Retorna True se for dispositivo móvel"""
        device_type = DeviceDetector.get_device_type(user_agent)
        return device_type in ['mobile', 'phablet']

    @staticmethod
    def is_tablet(user_agent):
        """Retorna True se for tablet"""
        return DeviceDetector.get_device_type(user_agent) == 'tablet'

    @staticmethod
    def is_touch_device(user_agent):
        """Retorna True se for dispositivo touch (mobile/tablet)"""
        device_type = DeviceDetector.get_device_type(user_agent)
        return device_type in ['mobile', 'tablet', 'phablet']

def device_detection_middleware(app):
    """Middleware Flask para detectar dispositivos"""

    @app.before_request
    def detect_device():
        """Executado antes de cada requisição para detectar o dispositivo"""
        user_agent = request.headers.get('User-Agent', '')

        # Detectar tipo de dispositivo
        device_type = DeviceDetector.get_device_type(user_agent)

        # Definir variáveis globais para uso nos templates
        g.device_type = device_type
        g.is_mobile = DeviceDetector.is_mobile(user_agent)
        g.is_tablet = DeviceDetector.is_tablet(user_agent)
        g.is_touch = DeviceDetector.is_touch_device(user_agent)
        g.is_desktop = device_type == 'desktop'

        # Adicionar classes CSS baseadas no dispositivo
        device_classes = []
        if g.is_mobile:
            device_classes.append('device-mobile')
        if g.is_tablet:
            device_classes.append('device-tablet')
        if g.is_touch:
            device_classes.append('device-touch')
        if g.is_desktop:
            device_classes.append('device-desktop')

        g.device_classes = ' '.join(device_classes)

        # Log para debug (remover em produção)
        print(f"📱 Dispositivo detectado: {device_type} | User-Agent: {user_agent[:100]}...")

    return app

def get_device_context():
    """Retorna contexto de dispositivo para templates"""
    return {
        'device_type': getattr(g, 'device_type', 'desktop'),
        'is_mobile': getattr(g, 'is_mobile', False),
        'is_tablet': getattr(g, 'is_tablet', False),
        'is_touch': getattr(g, 'is_touch', False),
        'is_desktop': getattr(g, 'is_desktop', True),
        'device_classes': getattr(g, 'device_classes', 'device-desktop')
    }

# Função helper para templates Jinja2
def device_helper():
    """Helper function para templates Jinja2"""
    return get_device_context()
