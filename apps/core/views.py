from django.shortcuts import render
from apps.productos.models import Producto, Sabor


def homepage(request):
    # 4 productos destacados (helados activos)
    destacados = Producto.objects.filter(
        activo=True,
        tipo__in=["helado_cuarto", "helado_medio", "helado_kilo"]
    )[:4]

    # Sabores disponibles (para mostrar en la sección de sabores)
    sabores = Sabor.objects.filter(activo=True).order_by("nombre")

    context = {
        "destacados": destacados,
        "sabores":    sabores,
    }
    return render(request, "core/homepage.html", context)