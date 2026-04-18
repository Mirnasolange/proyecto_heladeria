from decimal import Decimal


def carrito_context(request):
    """
    Inyecta en todos los templates:
      - carrito_items   → lista de ítems en sesión
      - carrito_total   → suma total
      - carrito_cantidad→ número de ítems (para el badge del navbar)
    """
    carrito = request.session.get("carrito", [])
    total   = sum(Decimal(str(item.get("subtotal", 0))) for item in carrito)

    return {
        "carrito_items":    carrito,
        "carrito_cantidad": len(carrito),
        "carrito_total":    total,
    }