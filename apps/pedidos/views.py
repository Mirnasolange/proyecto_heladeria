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
    """
    Recibe JSON:
    {
      "items": [...],
      "pagos": [
        {"tipo": "EFECTIVO", "subtipo": "", "monto": 1500, "referencia": ""},
        {"tipo": "DIGITAL",  "subtipo": "MERCADOPAGO", "monto": 500, "referencia": "ABC123"}
      ],
      "nombre": "Juan"
    }
    Reglas:
    - Máximo 2 pagos
    - La suma de pagos debe >= total del pedido (si excede se devuelve cambio, no es error)
    - Efectivo no requiere subtipo ni referencia
    - Tarjeta requiere subtipo (DEBITO / CREDITO)
    - Digital requiere subtipo (MERCADOPAGO / TRANSFERENCIA)
    """

    try:
        data       = json.loads(request.body)
        items_data = data.get("items", [])
        pagos_data = data.get("pagos", [])
        nombre     = data.get("nombre", "Mostrador").strip() or "Mostrador"

        # ── Validaciones de entrada ──────────────────────────────
        if not items_data:
            return JsonResponse({"ok": False, "error": "Sin ítems en el ticket."}, status=400)

        if not pagos_data:
            return JsonResponse({"ok": False, "error": "Agregá al menos un pago."}, status=400)

        if len(pagos_data) > 2:
            return JsonResponse({"ok": False, "error": "Máximo 2 formas de pago."}, status=400)

        # Validar estructura de cada pago antes de tocar la BD
        SUBTIPOS_POR_TIPO = {
            Pago.TIPO_TARJETA: [Pago.SUBTIPO_DEBITO, Pago.SUBTIPO_CREDITO],
            Pago.TIPO_DIGITAL: [Pago.SUBTIPO_MERCADOPAGO, Pago.SUBTIPO_TRANSFERENCIA],
        }
        TIPOS_VALIDOS = [Pago.TIPO_EFECTIVO, Pago.TIPO_TARJETA, Pago.TIPO_DIGITAL]

        suma_pagos = Decimal("0")
        for i, p in enumerate(pagos_data, 1):
            tipo    = p.get("tipo", "")
            subtipo = p.get("subtipo", "")
            monto   = p.get("monto")

            if tipo not in TIPOS_VALIDOS:
                return JsonResponse({"ok": False, "error": f"Pago {i}: tipo inválido '{tipo}'."}, status=400)

            if monto is None or not str(monto).strip():
                return JsonResponse({"ok": False, "error": f"Pago {i}: ingresá el monto."}, status=400)

            try:
                monto_dec = Decimal(str(monto))
            except Exception:
                return JsonResponse({"ok": False, "error": f"Pago {i}: monto inválido."}, status=400)

            if monto_dec <= 0:
                return JsonResponse({"ok": False, "error": f"Pago {i}: el monto debe ser mayor a 0."}, status=400)

            if tipo in SUBTIPOS_POR_TIPO:
                validos = SUBTIPOS_POR_TIPO[tipo]
                if subtipo not in validos:
                    return JsonResponse({
                        "ok": False,
                        "error": f"Pago {i}: seleccioná el subtipo ({' / '.join(validos)})."
                    }, status=400)

            suma_pagos += monto_dec

        # ── Calcular total del ticket para validar cobertura ─────
        # (lo hacemos aquí, antes de crear nada, para no dejar pedidos huérfanos)
        total_ticket = Decimal("0")
        for it in items_data:
            if it.get("libre"):
                total_ticket += Decimal(str(it.get("libre_precio", 0))) * int(it.get("cantidad", 1))
            else:
                prod = Producto.objects.get(pk=it["producto_id"])
                total_ticket += prod.precio * int(it.get("cantidad", 1))

        if suma_pagos < total_ticket:
            falta = total_ticket - suma_pagos
            return JsonResponse({
                "ok": False,
                "error": f"Los pagos suman ${float(suma_pagos):,.0f} pero el total es ${float(total_ticket):,.0f}. Falta ${float(falta):,.0f}."
            }, status=400)

        # ── Determinar método principal para el pedido ───────────
        tipos_usados = list({p["tipo"] for p in pagos_data})
        if len(tipos_usados) == 1:
            metodo_principal = tipos_usados[0]
        else:
            metodo_principal = "MIXTO"

        # ── Crear pedido ─────────────────────────────────────────
        pedido = Pedido.objects.create(
            cliente_nombre        = nombre,
            cliente_telefono      = "-",
            tipo_pedido           = Pedido.TIPO_MOSTRADOR,
            tipo_entrega          = Pedido.ENTREGA_RETIRO,
            estado                = Pedido.ESTADO_LISTO,
            metodo_pago_principal = metodo_principal,
        )

        # ── Crear ítems + descontar stock ────────────────────────
        for it in items_data:
            if it.get("libre"):
                precio   = Decimal(str(it.get("libre_precio", 0)))
                cantidad = int(it.get("cantidad", 1))
                ItemPedido.objects.create(
                    pedido          = pedido,
                    producto        = None,
                    cantidad        = cantidad,
                    precio_unitario = precio,
                    subtotal        = precio * cantidad,
                    comentarios     = it.get("libre_desc", "Ítem libre"),
                )
            else:
                producto = Producto.objects.get(pk=it["producto_id"])
                cantidad = int(it.get("cantidad", 1))
                ItemPedido.objects.create(
                    pedido          = pedido,
                    producto        = producto,
                    cantidad        = cantidad,
                    precio_unitario = producto.precio,
                    subtotal        = producto.precio * cantidad,
                )
                producto.descontar_stock(cantidad)

        pedido.calcular_total()

        # ── Crear pagos ──────────────────────────────────────────
        for p in pagos_data:
            Pago.objects.create(
                pedido     = pedido,
                tipo       = p["tipo"],
                subtipo    = p.get("subtipo", ""),
                monto      = Decimal(str(p["monto"])),
                estado     = Pago.ESTADO_APROBADO,
                referencia = p.get("referencia", "").strip(),
            )

        # ── Registrar en caja ────────────────────────────────────
        # Solo el efectivo entra en caja física; digital/tarjeta se registran
        # igual para trazabilidad pero marcados en la descripción.
        hoy  = timezone.now().date()
        caja = CajaDiaria.objects.filter(fecha=hoy, cerrada=False).first()
        if caja:
            MovimientoCaja.objects.create(
                caja        = caja,
                pedido      = pedido,
                tipo        = MovimientoCaja.TIPO_INGRESO,
                monto       = pedido.total,
                descripcion = f"POS – {pedido.numero} – {nombre}",
            )
            caja.calcular_cierre_esperado()
            caja.save(update_fields=["monto_cierre_esperado"])

        # Vuelto: solo aplica si hay pago en efectivo
        monto_ef = sum(
            Decimal(str(p["monto"])) for p in pagos_data if p["tipo"] == Pago.TIPO_EFECTIVO
        )
        vuelto = max(Decimal("0"), suma_pagos - pedido.total) if monto_ef > 0 else Decimal("0")

        return JsonResponse({
            "ok":     True,
            "numero": pedido.numero,
            "total":  float(pedido.total),
            "vuelto": float(vuelto),
        })

    except Producto.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Producto no encontrado."}, status=400)
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