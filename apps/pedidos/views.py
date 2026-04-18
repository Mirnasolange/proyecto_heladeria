import json
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.productos.models import Producto, Sabor, Topping
from .models import Pedido, ItemPedido, ItemPedidoSabor, ItemPedidoTopping
from apps.pagos.models import Pago, CajaDiaria, MovimientoCaja


# ─────────────────────────────────────────────
# HELPERS DE SESIÓN
# ─────────────────────────────────────────────

def get_carrito(request):
    """Devuelve el carrito de la sesión. Siempre es una lista de dicts."""
    return request.session.get("carrito", [])


def set_carrito(request, carrito):
    request.session["carrito"] = carrito
    request.session.modified = True


def calcular_subtotal_item(item):
    """
    Recalcula el subtotal de un ítem del carrito.
    Primer topping gratis, los siguientes +$100 c/u.
    """
    precio       = Decimal(str(item["precio_unitario"]))
    cantidad     = item["cantidad"]
    n_toppings   = len(item.get("toppings_ids", []))
    extra_top    = max(0, n_toppings - 1) * Decimal("100")
    return float((precio * cantidad) + extra_top)


def calcular_total_carrito(carrito):
    return sum(Decimal(str(item["subtotal"])) for item in carrito)


# ─────────────────────────────────────────────
# CARRITO
# ─────────────────────────────────────────────

@require_POST
def agregar_al_carrito(request):
    """
    Recibe POST con:
      producto_id, cantidad, sabores_ids (lista), toppings_ids (lista), comentarios
    Agrega el ítem a la sesión y redirige al carrito.
    """
    try:
        producto_id  = int(request.POST.get("producto_id"))
        cantidad     = int(request.POST.get("cantidad", 1))
        sabores_ids  = request.POST.getlist("sabores_ids")
        toppings_ids = request.POST.getlist("toppings_ids")
        comentarios  = request.POST.get("comentarios", "").strip()
    except (ValueError, TypeError):
        messages.error(request, "Datos inválidos. Intentá de nuevo.")
        return redirect("productos:catalogo")

    producto = get_object_or_404(Producto, pk=producto_id, activo=True)

    # Validar límite de sabores si es helado
    if producto.es_helado and len(sabores_ids) > producto.limite_sabores:
        messages.warning(
            request,
            f"Podés elegir hasta {producto.limite_sabores} sabores para {producto.nombre}. "
            "Si querés más, aclaralo en comentarios."
        )
        return redirect("productos:detalle", pk=producto_id)

    # Obtener nombres para mostrar en el carrito
    sabores_objs  = Sabor.objects.filter(id__in=sabores_ids)
    toppings_objs = Topping.objects.filter(id__in=toppings_ids)

    item = {
        "producto_id":     producto.id,
        "producto_nombre": producto.nombre,
        "producto_tipo":   producto.get_tipo_display(),
        "precio_unitario": float(producto.precio),
        "cantidad":        cantidad,
        "sabores_ids":     [int(s) for s in sabores_ids],
        "sabores_nombres": [s.nombre for s in sabores_objs],
        "toppings_ids":    [int(t) for t in toppings_ids],
        "toppings_nombres":[t.nombre for t in toppings_objs],
        "comentarios":     comentarios,
    }
    item["subtotal"] = calcular_subtotal_item(item)

    carrito = get_carrito(request)
    carrito.append(item)
    set_carrito(request, carrito)

    messages.success(request, f"✔ {producto.nombre} agregado al carrito.")
    return redirect("pedidos:carrito")


@require_POST
def quitar_del_carrito(request):
    indice = int(request.POST.get("indice", -1))
    carrito = get_carrito(request)
    if 0 <= indice < len(carrito):
        nombre = carrito[indice]["producto_nombre"]
        carrito.pop(indice)
        set_carrito(request, carrito)
        messages.success(request, f"'{nombre}' eliminado del carrito.")
    return redirect("pedidos:carrito")


def carrito(request):
    carrito = get_carrito(request)
    total   = calcular_total_carrito(carrito)
    context = {
        "carrito": carrito,
        "total":   total,
        "enumerate": enumerate,   # para usar enumerate en el template
    }
    return render(request, "pedidos/carrito.html", context)


# ─────────────────────────────────────────────
# CHECKOUT
# ─────────────────────────────────────────────

def checkout(request):
    carrito_items = get_carrito(request)
    if not carrito_items:
        messages.warning(request, "Tu carrito está vacío.")
        return redirect("productos:catalogo")

    total = calcular_total_carrito(carrito_items)

    if request.method == "POST":
        # ── Datos del cliente ──
        nombre   = request.POST.get("nombre", "").strip()
        telefono = request.POST.get("telefono", "").strip()
        entrega  = request.POST.get("tipo_entrega", Pedido.ENTREGA_RETIRO)
        direccion = request.POST.get("direccion_entrega", "").strip()
        metodo_pago = request.POST.get("metodo_pago", Pedido.PAGO_EFECTIVO)
        comentarios = request.POST.get("comentarios", "").strip()

        # Pagos (puede ser mixto)
        monto_efectivo = request.POST.get("monto_efectivo", "").strip()
        monto_mp       = request.POST.get("monto_mp", "").strip()

        # Validaciones básicas
        if not nombre or not telefono:
            messages.error(request, "Nombre y teléfono son obligatorios.")
            return render(request, "pedidos/checkout.html", {
                "carrito": carrito_items, "total": total
            })

        if entrega == Pedido.ENTREGA_DELIVERY and not direccion:
            messages.error(request, "Ingresá la dirección para el delivery.")
            return render(request, "pedidos/checkout.html", {
                "carrito": carrito_items, "total": total
            })

        # ── Crear el pedido ──
        pedido = Pedido.objects.create(
            cliente_nombre        = nombre,
            cliente_telefono      = telefono,
            tipo_pedido           = Pedido.TIPO_WEB,
            tipo_entrega          = entrega,
            direccion_entrega     = direccion,
            estado                = Pedido.ESTADO_RECIBIDO,
            metodo_pago_principal = metodo_pago,
            comentarios           = comentarios,
        )

        # ── Crear ítems ──
        for item in carrito_items:
            item_obj = ItemPedido.objects.create(
                pedido          = pedido,
                producto_id     = item["producto_id"],
                cantidad        = item["cantidad"],
                precio_unitario = Decimal(str(item["precio_unitario"])),
                subtotal        = Decimal(str(item["subtotal"])),
                comentarios     = item.get("comentarios", ""),
            )
            # Sabores
            for orden, sabor_id in enumerate(item.get("sabores_ids", [])):
                ItemPedidoSabor.objects.create(
                    item_pedido_id = item_obj.id,
                    sabor_id       = sabor_id,
                    orden          = orden,
                )
            # Toppings
            for topping_id in item.get("toppings_ids", []):
                ItemPedidoTopping.objects.create(
                    item_pedido_id = item_obj.id,
                    topping_id     = topping_id,
                )

        # ── Calcular total real ──
        pedido.calcular_total()

        # ── Registrar pagos ──
        if metodo_pago == Pedido.PAGO_MIXTO:
            if monto_efectivo:
                Pago.objects.create(
                    pedido=pedido, tipo=Pago.TIPO_EFECTIVO,
                    monto=Decimal(monto_efectivo), estado=Pago.ESTADO_APROBADO
                )
            if monto_mp:
                Pago.objects.create(
                    pedido=pedido, tipo=Pago.TIPO_MP,
                    monto=Decimal(monto_mp), estado=Pago.ESTADO_PENDIENTE
                )
        elif metodo_pago == Pedido.PAGO_EFECTIVO:
            Pago.objects.create(
                pedido=pedido, tipo=Pago.TIPO_EFECTIVO,
                monto=pedido.total, estado=Pago.ESTADO_PENDIENTE
            )
        else:  # MercadoPago
            Pago.objects.create(
                pedido=pedido, tipo=Pago.TIPO_MP,
                monto=pedido.total, estado=Pago.ESTADO_PENDIENTE
            )

        # ── Registrar en caja del día (si está abierta) ──
        from django.utils import timezone
        hoy = timezone.now().date()
        caja = CajaDiaria.objects.filter(fecha=hoy, cerrada=False).first()
        if caja:
            MovimientoCaja.objects.create(
                caja        = caja,
                pedido      = pedido,
                tipo        = MovimientoCaja.TIPO_INGRESO,
                monto       = pedido.total,
                descripcion = f"Pedido {pedido.numero} – {pedido.get_metodo_pago_principal_display()}",
            )

        # ── Limpiar carrito ──
        set_carrito(request, [])

        messages.success(request, f"¡Pedido {pedido.numero} recibido! Te avisamos cuando esté listo.")
        return redirect("pedidos:confirmado", numero=pedido.numero)

    return render(request, "pedidos/checkout.html", {
        "carrito": carrito_items,
        "total":   total,
    })


def pedido_confirmado(request, numero):
    pedido = get_object_or_404(Pedido, numero=numero)
    return render(request, "pedidos/confirmado.html", {"pedido": pedido})


# ─────────────────────────────────────────────
# PANEL INTERNO – GESTIÓN DE PEDIDOS
# ─────────────────────────────────────────────

def gestion_pedidos(request):
    estado_filtro = request.GET.get("estado", "")
    pedidos = Pedido.objects.all().prefetch_related("items", "pagos")
    if estado_filtro:
        pedidos = pedidos.filter(estado=estado_filtro)

    context = {
        "pedidos":       pedidos,
        "estado_filtro": estado_filtro,
        "estados":       Pedido.ESTADO_CHOICES,
    }
    return render(request, "pedidos/gestion.html", context)


def detalle_pedido(request, numero):
    pedido = get_object_or_404(Pedido, numero=numero)
    items  = pedido.items.prefetch_related("sabores__sabor", "toppings__topping")
    pagos  = pedido.pagos.all()
    context = {
        "pedido": pedido,
        "items":  items,
        "pagos":  pagos,
        "estados": Pedido.ESTADO_CHOICES,
    }
    return render(request, "pedidos/detalle.html", context)


@require_POST
def cambiar_estado(request, numero):
    pedido     = get_object_or_404(Pedido, numero=numero)
    nuevo_estado = request.POST.get("estado")
    estados_validos = [e[0] for e in Pedido.ESTADO_CHOICES]
    if nuevo_estado in estados_validos:
        pedido.estado = nuevo_estado
        pedido.save(update_fields=["estado"])
        messages.success(request, f"Estado actualizado a: {pedido.get_estado_display()}")
    else:
        messages.error(request, "Estado inválido.")
    return redirect("pedidos:detalle", numero=numero)


# ─────────────────────────────────────────────
# VENTA RÁPIDA (MOSTRADOR)
# ─────────────────────────────────────────────

def venta_rapida(request):
    productos = Producto.objects.filter(activo=True)

    if request.method == "POST":
        producto_id = request.POST.get("producto_id")
        cantidad    = int(request.POST.get("cantidad", 1))
        metodo_pago = request.POST.get("metodo_pago", Pedido.PAGO_EFECTIVO)
        nombre      = request.POST.get("nombre", "Mostrador")
        telefono    = request.POST.get("telefono", "-")

        producto = get_object_or_404(Producto, pk=producto_id)

        pedido = Pedido.objects.create(
            cliente_nombre        = nombre,
            cliente_telefono      = telefono,
            tipo_pedido           = Pedido.TIPO_MOSTRADOR,
            tipo_entrega          = Pedido.ENTREGA_RETIRO,
            estado                = Pedido.ESTADO_LISTO,
            metodo_pago_principal = metodo_pago,
        )
        item = ItemPedido.objects.create(
            pedido          = pedido,
            producto        = producto,
            cantidad        = cantidad,
            precio_unitario = producto.precio,
            subtotal        = producto.precio * cantidad,
        )
        pedido.calcular_total()

        Pago.objects.create(
            pedido  = pedido,
            tipo    = Pago.TIPO_EFECTIVO if metodo_pago == Pedido.PAGO_EFECTIVO else Pago.TIPO_MP,
            monto   = pedido.total,
            estado  = Pago.ESTADO_APROBADO,
        )

        from django.utils import timezone
        hoy  = timezone.now().date()
        caja = CajaDiaria.objects.filter(fecha=hoy, cerrada=False).first()
        if caja:
            MovimientoCaja.objects.create(
                caja        = caja,
                pedido      = pedido,
                tipo        = MovimientoCaja.TIPO_INGRESO,
                monto       = pedido.total,
                descripcion = f"Venta rápida – {producto.nombre}",
            )

        messages.success(request, f"Venta registrada: {pedido.numero}")
        return redirect("pedidos:gestion")

    return render(request, "pedidos/venta_rapida.html", {"productos": productos})