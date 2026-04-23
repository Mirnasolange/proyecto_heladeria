from django.urls import path
from . import views

app_name = 'pagos'

urlpatterns = [
    path('caja/',                views.caja_hoy,           name='caja_hoy'),
    path('caja/abrir/',          views.abrir_caja,         name='abrir_caja'),
    path('caja/cerrar/',         views.cerrar_caja,        name='cerrar_caja'),
    path('caja/egreso/',         views.registrar_egreso,   name='egreso'),
    path('metricas/',            views.metricas,           name='metricas'),
    path('stock/',               views.stock,              name='stock'),
    path('stock/ajuste/',        views.ajuste_stock,       name='ajuste_stock'),
    path('proveedores/export/',  views.exportar_proveedores, name='exportar_proveedores'),
    path('stock/alerta-email/',  views.alerta_stock_email, name='alerta_stock_email'),
    path('pos/movimientos/',       views.pos_movimientos,       name='pos_movimientos'),
    path('pos/movimiento-manual/', views.pos_movimiento_manual, name='pos_movimiento_manual'),
    path('pos/corte/',             views.pos_corte,             name='pos_corte'),
    path('sesion/abrir/',       views.abrir_sesion_caja,   name='abrir_sesion'),
    path('sesion/datos-corte/', views.datos_corte_sesion,  name='datos_corte_sesion'),
    path('sesion/cerrar/',      views.cerrar_sesion_caja,  name='cerrar_sesion'),
    path('sesion/estado/',      views.estado_sesion,       name='estado_sesion'),
    ]