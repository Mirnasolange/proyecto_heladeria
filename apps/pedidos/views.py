import json
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from apps.productos.models import Producto, Sabor, Topping
from .models import Pedido, ItemPedido, ItemPedidoSabor, ItemPedidoTopping
from apps.pagos.models import Pago, CajaDiaria, MovimientoCaja
from apps.core.emails import notificar_pedido_recibido
from apps.core.emails import notificar_pedido_listo, notificar_en_camino



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


        # ── Descontar stock ──
        for item in carrito_items:
            try:
                from apps.productos.models import Producto
                producto = Producto.objects.get(pk=item["producto_id"])
                producto.descontar_stock(item["cantidad"])
            except Exception:
                pass  # no romper si algo falla      


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

        # ── Registrar en caja (según tipo de pago) ──
        es_delivery_efectivo = (
            entrega == Pedido.ENTREGA_DELIVERY and
            metodo_pago in [Pedido.PAGO_EFECTIVO, Pedido.PAGO_MIXTO]
        )

        if not es_delivery_efectivo:
            from django.utils import timezone
            hoy = timezone.now().date()
            caja = CajaDiaria.objects.filter(fecha=hoy, cerrada=False).first()
            if caja:
                MovimientoCaja.objects.create(
                    caja=caja,
                    pedido=pedido,
                    tipo=MovimientoCaja.TIPO_INGRESO,
                    monto=pedido.total,
                    descripcion=f"Pedido {pedido.numero} – {pedido.get_metodo_pago_principal_display()}",
                )            

        # ── Notificar por email ──
        notificar_pedido_recibido(pedido)

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

        # ── Registrar caja si es delivery efectivo entregado ──
        if (nuevo_estado == Pedido.ESTADO_ENTREGADO and
            pedido.tipo_entrega == Pedido.ENTREGA_DELIVERY and
            pedido.metodo_pago_principal in [Pedido.PAGO_EFECTIVO, Pedido.PAGO_MIXTO]):

            from django.utils import timezone
            from apps.pagos.models import CajaDiaria, MovimientoCaja

            hoy  = timezone.now().date()
            caja = CajaDiaria.objects.filter(fecha=hoy, cerrada=False).first()

            if caja:
                ya_registrado = pedido.movimientos_caja.exists()
                if not ya_registrado:
                    MovimientoCaja.objects.create(
                        caja=caja,
                        pedido=pedido,
                        tipo=MovimientoCaja.TIPO_INGRESO,
                        monto=pedido.total,
                        descripcion=f"Delivery entregado – {pedido.numero}",
                    )
                    caja.calcular_cierre_esperado()
                    caja.save(update_fields=["monto_cierre_esperado"])

        # ── Notificaciones por cambio de estado ──
        if nuevo_estado == Pedido.ESTADO_LISTO:
            notificar_pedido_listo(pedido)
        elif nuevo_estado == Pedido.ESTADO_EN_CAMINO:
            notificar_en_camino(pedido)
        messages.success(request, f"Estado actualizado a: {pedido.get_estado_display()}")
    else:
        messages.error(request, "Estado inválido.")
    return redirect("pedidos:detalle", numero=numero)


# ─────────────────────────────────────────────
# REPARTOS (DELIVERY)
# ─────────────────────────────────────────────

def repartos(request):
    """Lista de pedidos en delivery, agrupados por estado."""
    
    en_camino = Pedido.objects.filter(
        tipo_entrega = Pedido.ENTREGA_DELIVERY,
        estado__in = [Pedido.ESTADO_LISTO, Pedido.ESTADO_EN_CAMINO],
    ).order_by("fecha_creacion")

    hoy = timezone.now().date()

    entregados_hoy = Pedido.objects.filter(
        tipo_entrega = Pedido.ENTREGA_DELIVERY,
        estado = Pedido.ESTADO_ENTREGADO,
        fecha_actualizacion__date = hoy,
    ).order_by("-fecha_actualizacion")

    return render(request, "pedidos/repartos.html", {
        "en_camino": en_camino,
        "entregados_hoy": entregados_hoy,
    })


# ─────────────────────────────────────────────
# POS (PUNTO DE VENTA)
# ─────────────────────────────────────────────

def pos(request):
    """Pantalla principal del Punto de Venta (POS)."""
    from apps.productos.models import Producto
    productos = Producto.objects.filter(activo=True).order_by("tipo", "nombre")
    context = {"productos": productos}
    return render(request, "pedidos/pos.html", context)


@require_POST
def pos_cobrar(request):
    from apps.pagos.models import CajaDiaria, MovimientoCaja, Pago
    from apps.productos.models import Producto
    from django.utils import timezone

    try:
        data         = json.loads(request.body)
        items_data   = data.get("items", [])
        metodo_pago  = data.get("metodo_pago", "EFECTIVO")
        monto_pagado = Decimal(str(data.get("monto_pagado", "0")))
        monto_mp     = Decimal(str(data.get("monto_mp", "0")))
        nombre       = data.get("nombre", "Mostrador").strip() or "Mostrador"

        if not items_data:
            return JsonResponse({"ok": False, "error": "Sin ítems"}, status=400)

        pedido = Pedido.objects.create(
            cliente_nombre        = nombre,
            cliente_telefono      = "-",
            tipo_pedido           = Pedido.TIPO_MOSTRADOR,
            tipo_entrega          = Pedido.ENTREGA_RETIRO,
            estado                = Pedido.ESTADO_LISTO,
            metodo_pago_principal = metodo_pago,
        )

        for it in items_data:
            es_libre = it.get("libre", False)

            if es_libre:
                # Ítem de precio y descripción libre — no tiene producto en BD
                precio   = Decimal(str(it.get("libre_precio", 0)))
                cantidad = int(it.get("cantidad", 1))
                ItemPedido.objects.create(
                    pedido          = pedido,
                    producto        = None,          # null permitido
                    cantidad        = cantidad,
                    precio_unitario = precio,
                    subtotal        = precio * cantidad,
                    comentarios     = it.get("libre_desc", "Ítem libre"),
                )
            else:
                producto = Producto.objects.get(pk=it["producto_id"])
                cantidad = int(it.get("cantidad", 1))
                subtotal = producto.precio * cantidad

                ItemPedido.objects.create(
                    pedido          = pedido,
                    producto        = producto,
                    cantidad        = cantidad,
                    precio_unitario = producto.precio,
                    subtotal        = subtotal,
                )

                # ── Descontar stock del producto e insumo asociado ──
                producto.descontar_stock(cantidad)

        pedido.calcular_total()

        # ── Pagos ──
        if metodo_pago == "MIXTO":
            if monto_pagado > 0:
                Pago.objects.create(pedido=pedido, tipo=Pago.TIPO_EFECTIVO, monto=monto_pagado, estado=Pago.ESTADO_APROBADO)
            if monto_mp > 0:
                Pago.objects.create(pedido=pedido, tipo=Pago.TIPO_MP, monto=monto_mp, estado=Pago.ESTADO_APROBADO)
        elif metodo_pago == "MERCADOPAGO":
            Pago.objects.create(pedido=pedido, tipo=Pago.TIPO_MP, monto=pedido.total, estado=Pago.ESTADO_APROBADO)
        else:
            Pago.objects.create(pedido=pedido, tipo=Pago.TIPO_EFECTIVO, monto=pedido.total, estado=Pago.ESTADO_APROBADO)

        # ── Caja ──
        hoy  = timezone.now().date()
        caja = CajaDiaria.objects.filter(fecha=hoy, cerrada=False).first()
        if caja:
            MovimientoCaja.objects.create(
                caja=caja, pedido=pedido,
                tipo=MovimientoCaja.TIPO_INGRESO,
                monto=pedido.total,
                descripcion=f"POS – {pedido.numero} – {nombre}",
            )
            caja.calcular_cierre_esperado()
            caja.save(update_fields=["monto_cierre_esperado"])

        vuelto = float(monto_pagado) - float(pedido.total) if metodo_pago in ["EFECTIVO", "MIXTO"] else 0

        return JsonResponse({"ok": True, "numero": pedido.numero, "total": float(pedido.total), "vuelto": max(0, vuelto)})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"ok": False, "error": str(e)}, status=500)
    
    # ── Cancelar venta ──────────────────────────────────
@require_POST
def cancelar_venta(request):
    """Cambia el estado del pedido a CANCELADO y revierte el movimiento de caja."""
    from apps.pagos.models import CajaDiaria, MovimientoCaja
    from django.utils import timezone
    try:
        data   = json.loads(request.body)
        numero = data.get("numero")
        pedido = Pedido.objects.get(numero=numero)
 
        if pedido.estado == Pedido.ESTADO_CANCELADO:
            return JsonResponse({"ok": False, "error": "Ya estaba cancelado."})
 
        pedido.estado = Pedido.ESTADO_CANCELADO
        pedido.save(update_fields=["estado"])
 
        # Revertir movimiento de caja: crear egreso compensatorio
        hoy  = timezone.now().date()
        caja = CajaDiaria.objects.filter(fecha=hoy, cerrada=False).first()
        if caja and pedido.movimientos_caja.filter(tipo=MovimientoCaja.TIPO_INGRESO).exists():
            MovimientoCaja.objects.create(
                caja        = caja,
                pedido      = pedido,
                tipo        = MovimientoCaja.TIPO_EGRESO,
                monto       = pedido.total,
                descripcion = f"Cancelación {pedido.numero}",
            )
            caja.calcular_cierre_esperado()
            caja.save(update_fields=["monto_cierre_esperado"])
 
        return JsonResponse({"ok": True})
    except Pedido.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Pedido no encontrado."})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})