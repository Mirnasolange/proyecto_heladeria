# apps/productos/views.py, apps/pedidos/views.py, apps/pagos/views.py
from django.http import HttpResponse

def catalogo(request):         return HttpResponse("próximamente")
def detalle_producto(request, pk): return HttpResponse("próximamente")
# (y así con cada función que el urls.py de esa app mencione)

def procesar_pago(request): return HttpResponse("Pago procesado")
def detalle_pago(request, pk): return HttpResponse(f"Detalle del pago {pk}")
def gestion_pagos(request): return HttpResponse("Gestión de pagos funcionando")
def caja_hoy(request): return HttpResponse("Caja del día funcionando")
def abrir_caja(request): return HttpResponse("Caja abierta correctamente")
def cerrar_caja(request): return HttpResponse("Caja cerrada correctamente")
def registrar_egreso(request): return HttpResponse("Egreso registrado correctamente")
def metricas(request): return HttpResponse("Métricas de pagos funcionando")
def stock(request): return HttpResponse("Stock funcionando")
def ajuste_stock(request): return HttpResponse("Ajuste de stock funcionando")
def exportar_proveedores(request): return HttpResponse("Exportación de proveedores funcionando")





