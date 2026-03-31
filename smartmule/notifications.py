import logging
from plyer import notification # Importamos la librería para enviar notificaciones nativas (plyer es multiplataforma)

logger = logging.getLogger("SmartMule.notifications")

# Módulo para enviar notificaciones
def send_notification(title: str, message: str, is_critical: bool = False):

    """
    Envía una notificación nativa al escritorio del usuario.
    
    Args:
        title (str): Título principal de la notificación.
        message (str): Mensaje descriptivo.
        is_critical (bool): Aumenta el tiempo que la notificación permanece en pantalla.
    """

    try:

        # Definimos el tiempo de la notificación (más largo si es crítica)
        timeout = 10 if is_critical else 5
        
        notification.notify( # Envía la notificación 
            title=f"SmartMule 🫏 - {title}",
            message=message,
            app_name="SmartMule", 
            timeout=timeout
        )

    except Exception as e:
        # Las notificaciones pueden fallar en entornos sin GUI o si faltan dependencias del SO (e.g. en Linux headless).
        # Lo registramos como debug para no sobrecargar los logs principales.
        logger.debug(f"ℹ️  No se pudo lanzar la notificación de escritorio: {e}")
