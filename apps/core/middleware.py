from django.shortcuts import redirect
from django.conf import settings

PANEL_PREFIXES = [
    "/pedidos/gestion",
    "/pedidos/pos",
    "/pedidos/repartos",
    "/pedidos/venta_rapida",
    "/pagos/",
]

class PanelLoginMiddleware:
    """
    Redirige a /accounts/login/ si el usuario no está autenticado
    e intenta acceder a cualquier URL del panel interno.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        es_panel = any(path.startswith(p) for p in PANEL_PREFIXES)
        if es_panel and not request.user.is_authenticated:
            return redirect(f"{settings.LOGIN_URL}?next={path}")
        return self.get_response(request)