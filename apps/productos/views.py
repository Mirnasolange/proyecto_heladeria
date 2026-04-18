from django.shortcuts import render, get_object_or_404
from .models import Producto, Sabor, Topping


def catalogo(request):
    tipo_filtro = request.GET.get("tipo", "")

    productos = Producto.objects.filter(activo=True)
    if tipo_filtro:
        productos = productos.filter(tipo=tipo_filtro)

    context = {
        "productos":    productos,
        "tipo_filtro":  tipo_filtro,
        "tipos":        Producto.TIPO_CHOICES,
    }
    return render(request, "productos/catalogo.html", context)


def detalle_producto(request, pk):
    producto = get_object_or_404(Producto, pk=pk, activo=True)

    sabores  = Sabor.objects.filter(activo=True).order_by("nombre")
    toppings = Topping.objects.filter(activo=True)

    context = {
        "producto":       producto,
        "sabores":        sabores,
        "toppings":       toppings,
        "limite_sabores": producto.limite_sabores,
    }
    return render(request, "productos/detalle.html", context)