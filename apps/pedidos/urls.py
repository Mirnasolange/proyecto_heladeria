from django.urls import path
from . import views

app_name = 'pedidos'

urlpatterns = [
    # Web (cliente)
    path('carrito/',           views.carrito,           name='carrito'),
    path('carrito/agregar/',   views.agregar_al_carrito, name='agregar_carrito'),
    path('carrito/quitar/',    views.quitar_del_carrito, name='quitar_carrito'),
    path('checkout/',          views.checkout,           name='checkout'),
    path('confirmado/<str:numero>/', views.pedido_confirmado, name='confirmado'),

    # Panel interno (gestión)
    path('gestion/',                       views.gestion_pedidos,  name='gestion'),
    path('gestion/<str:numero>/',          views.detalle_pedido,   name='detalle'),
    path('gestion/<str:numero>/estado/',   views.cambiar_estado,   name='cambiar_estado'),
    path('pos/',            views.pos,          name='pos'),
    path('pos/cobrar/',     views.pos_cobrar,   name='pos_cobrar'),
    path('repartos/',      views.repartos,    name='repartos'),
    path('cancelar/', views.cancelar_venta, name='cancelar_venta'),

]