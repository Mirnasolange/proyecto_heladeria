from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum, Count, Avg
from django.http import HttpResponse
from decimal import Decimal
import datetime

from .models import CajaDiaria, MovimientoCaja, AjusteStock, InsumoStock, Pago
from apps.pedidos.models import Pedido, ItemPedido, ItemPedidoSabor
from apps.productos.models import Sabor, Producto


# ─────────────────────────────────────────────
# CAJA
# ─────────────────────────────────────────────

def caja_hoy(request):
    hoy  = timezone.now().date()
    caja = CajaDiaria.objects.filter(fecha=hoy).first()

    if caja:
        movimientos = caja.movimientos.all()
        ingresos = caja.movimientos.filter(
            tipo=MovimientoCaja.TIPO_INGRESO
        ).aggregate(total=Sum("monto"))["total"] or 0

        egresos = caja.movimientos.filter(
            tipo=MovimientoCaja.TIPO_EGRESO
        ).aggregate(total=Sum("monto"))["total"] or 0
    else:
        movimientos = []
        ingresos = 0
        egresos = 0

    context = {
        "caja": caja,
        "hoy": hoy,
        "movimientos": movimientos,
        "ingresos": ingresos,
        "egresos": egresos,
    }
    return render(request, "pagos/caja.html", context)


def abrir_caja(request):
    if request.method == "POST":
        hoy = timezone.now().date()
        if CajaDiaria.objects.filter(fecha=hoy).exists():
            messages.warning(request, "Ya hay una caja abierta para hoy.")
            return redirect("pagos:caja_hoy")

        monto_inicial = Decimal(request.POST.get("monto_inicial", "0"))
        CajaDiaria.objects.create(fecha=hoy, monto_inicial=monto_inicial)
        messages.success(request, f"Caja abierta con ${monto_inicial} iniciales.")
    return redirect("pagos:caja_hoy")


def cerrar_caja(request):
    if request.method == "POST":
        hoy  = timezone.now().date()
        caja = get_object_or_404(CajaDiaria, fecha=hoy, cerrada=False)
        monto_real = Decimal(request.POST.get("monto_real", "0"))
        caja.cerrar(monto_real)
        messages.success(request, "Caja cerrada correctamente.")
    return redirect("pagos:caja_hoy")


def registrar_egreso(request):
    if request.method == "POST":
        hoy  = timezone.now().date()
        caja = CajaDiaria.objects.filter(fecha=hoy, cerrada=False).first()
        if not caja:
            messages.error(request, "No hay caja abierta hoy.")
            return redirect("pagos:caja_hoy")

        monto       = Decimal(request.POST.get("monto", "0"))
        descripcion = request.POST.get("descripcion", "Egreso manual")

        MovimientoCaja.objects.create(
            caja        = caja,
            tipo        = MovimientoCaja.TIPO_EGRESO,
            monto       = monto,
            descripcion = descripcion,
        )
        caja.calcular_cierre_esperado()
        caja.save(update_fields=["monto_cierre_esperado"])
        messages.success(request, f"Egreso de ${monto} registrado.")
    return redirect("pagos:caja_hoy")


# ─────────────────────────────────────────────
# MÉTRICAS
# ─────────────────────────────────────────────

def metricas(request):
    # Rango de fechas (default: últimos 30 días)
    hoy        = timezone.now().date()
    fecha_desde = request.GET.get("desde", str(hoy - datetime.timedelta(days=30)))
    fecha_hasta = request.GET.get("hasta", str(hoy))

    try:
        desde = datetime.date.fromisoformat(fecha_desde)
        hasta = datetime.date.fromisoformat(fecha_hasta)
    except ValueError:
        desde = hoy - datetime.timedelta(days=30)
        hasta = hoy

    pedidos_qs = Pedido.objects.filter(
        fecha_creacion__date__gte=desde,
        fecha_creacion__date__lte=hasta,
    ).exclude(estado=Pedido.ESTADO_CANCELADO)

    # KPIs principales
    total_ventas   = pedidos_qs.aggregate(Sum("total"))["total__sum"] or Decimal("0")
    cantidad_pedidos = pedidos_qs.count()
    ticket_promedio  = (total_ventas / cantidad_pedidos) if cantidad_pedidos else Decimal("0")

    # Ventas por método de pago
    ventas_por_pago = (
        pedidos_qs
        .values("metodo_pago_principal")
        .annotate(total=Sum("total"), cantidad=Count("id"))
        .order_by("-total")
    )

    # Productos más vendidos
    productos_top = (
        ItemPedido.objects
        .filter(pedido__in=pedidos_qs)
        .values("producto__nombre", "producto__tipo")
        .annotate(unidades=Sum("cantidad"), ingresos=Sum("subtotal"))
        .order_by("-unidades")[:10]
    )

    # Sabores más pedidos
    sabores_top = (
        ItemPedidoSabor.objects
        .filter(item_pedido__pedido__in=pedidos_qs)
        .values("sabor__nombre")
        .annotate(apariciones=Count("id"))
        .order_by("-apariciones")[:10]
    )

    # Pedidos por día (para gráfico)
    pedidos_por_dia = (
        pedidos_qs
        .values("fecha_creacion__date")
        .annotate(total_dia=Sum("total"), cantidad_dia=Count("id"))
        .order_by("fecha_creacion__date")
    )

    context = {
        "desde":            desde,
        "hasta":            hasta,
        "total_ventas":     total_ventas,
        "cantidad_pedidos": cantidad_pedidos,
        "ticket_promedio":  ticket_promedio,
        "ventas_por_pago":  ventas_por_pago,
        "productos_top":    productos_top,
        "sabores_top":      sabores_top,
        "pedidos_por_dia":  pedidos_por_dia,
    }
    return render(request, "pagos/metricas.html", context)


# ─────────────────────────────────────────────
# STOCK
# ─────────────────────────────────────────────

def stock(request):
    from apps.productos.models import Sabor
    from apps.pedidos.models import ItemPedidoSabor

    # Período de análisis para proyección: últimos 14 días
    hoy      = timezone.now().date()
    hace_14  = hoy - datetime.timedelta(days=14)

    # Consumo promedio diario por sabor (en kg) basado en ventas reales
    consumo_qs = (
        ItemPedidoSabor.objects
        .filter(item_pedido__pedido__fecha_creacion__date__gte=hace_14)
        .values("sabor_id")
        .annotate(apariciones=Count("id"))
    )
    consumo_map = {}
    for row in consumo_qs:
        # Aproximamos: cada aparición ≈ 0.05 kg (ajustable)
        kg_por_dia = (row["apariciones"] * 0.05) / 14
        consumo_map[row["sabor_id"]] = round(kg_por_dia, 4)

    sabores_data = []
    alertas      = []

    for sabor in Sabor.objects.all().order_by("nombre"):
        consumo_diario = consumo_map.get(sabor.id, 0)
        if consumo_diario > 0:
            dias_restantes = sabor.stock_kg / Decimal(str(consumo_diario))
            dias_restantes = int(dias_restantes)
        else:
            dias_restantes = None   # sin datos de venta

        alerta = not sabor.disponible or (dias_restantes is not None and dias_restantes <= 3)

        sabores_data.append({
            "sabor":           sabor,
            "consumo_diario":  consumo_diario,
            "dias_restantes":  dias_restantes,
            "alerta":          alerta,
        })

        if alerta:
            alertas.append(sabor)

    insumos  = InsumoStock.objects.all()
    insumos_alerta = [i for i in insumos if i.bajo_stock]

    context = {
        "sabores_data":    sabores_data,
        "insumos":         insumos,
        "alertas":         alertas,
        "insumos_alerta":  insumos_alerta,
        "hay_alertas":     bool(alertas or insumos_alerta),
    }
    return render(request, "pagos/stock.html", context)


def ajuste_stock(request):
    if request.method == "POST":
        sabor_id    = request.POST.get("sabor_id")
        cantidad_kg = Decimal(request.POST.get("cantidad_kg", "0"))
        motivo      = request.POST.get("motivo", "")

        sabor = get_object_or_404(Sabor, pk=sabor_id)
        ajuste = AjusteStock.objects.create(
            sabor       = sabor,
            cantidad_kg = cantidad_kg,
            motivo      = motivo,
        )
        ajuste.aplicar()
        messages.success(
            request,
            f"Stock de {sabor.nombre} ajustado. Nuevo stock: {sabor.stock_kg} kg"
        )
    return redirect("pagos:stock")


def alerta_stock_email(request):
    """Envía un email de alerta de stock crítico al dueño. Llamado por AJAX."""
    if request.method != "POST":
        from django.http import JsonResponse
        return JsonResponse({"ok": False, "error": "Método no permitido"}, status=405)
 
    from apps.core.emails import notificar_stock_critico
    from django.http import JsonResponse
 
    sabores_criticos = []
    for sabor in Sabor.objects.filter(activo=True):
        if not sabor.disponible:
            sabores_criticos.append({"sabor": sabor, "motivo": "agotado"})
 
    insumos_criticos = [i for i in InsumoStock.objects.all() if i.bajo_stock]
 
    try:
        notificar_stock_critico(sabores_criticos, insumos_criticos)
        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})
 

# ─────────────────────────────────────────────
# EXPORTAR EXCEL PARA PROVEEDORES
# ─────────────────────────────────────────────

def exportar_proveedores(request):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return HttpResponse("openpyxl no instalado. Ejecutá: pip install openpyxl", status=500)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pedido a proveedores"

    # Estilos
    header_fill = PatternFill("solid", fgColor="3D1C02")
    header_font = Font(color="FFF8F0", bold=True)
    turquesa_fill = PatternFill("solid", fgColor="2EC4B6")

    headers = ["Sabor", "Stock actual (kg)", "Stock mínimo (kg)", "Sugerido pedir (kg)", "Cantidad a pedir"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    sabores = Sabor.objects.filter(activo=True).order_by("nombre")
    for row, sabor in enumerate(sabores, 2):
        # Sugerimos pedir el doble del mínimo menos lo que ya hay
        sugerido = max(Decimal("0"), (sabor.stock_minimo_kg * 2) - sabor.stock_kg)

        ws.cell(row=row, column=1, value=sabor.nombre)
        ws.cell(row=row, column=2, value=float(sabor.stock_kg))
        ws.cell(row=row, column=3, value=float(sabor.stock_minimo_kg))
        ws.cell(row=row, column=4, value=float(sugerido))
        # Columna editable para que el dueño ponga la cantidad real
        ws.cell(row=row, column=5, value=float(sugerido)).fill = turquesa_fill

    # Ancho de columnas
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = max_len + 4

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="pedido_proveedores.xlsx"'
    wb.save(response)
    return response