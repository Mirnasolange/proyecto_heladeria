from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum
from .models import Pago, CajaDiaria, MovimientoCaja, AjusteStock, InsumoStock


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display  = ("pedido", "tipo", "monto", "estado_badge", "fecha")
    list_filter   = ("tipo", "estado")
    search_fields = ("pedido__numero", "pedido__cliente_nombre")
    readonly_fields = ("fecha",)

    COLORES = {
        "PENDIENTE":  "#EF9F27",
        "APROBADO":   "#1D9E75",
        "RECHAZADO":  "#E24B4A",
    }

    def estado_badge(self, obj):
        color = self.COLORES.get(obj.estado, "#888")
        return format_html(
            '<span style="background:{};color:#fff;padding:3px 10px;border-radius:12px;font-size:12px">{}</span>',
            color, obj.get_estado_display()
        )
    estado_badge.short_description = "Estado"


class MovimientoCajaInline(admin.TabularInline):
    model         = MovimientoCaja
    extra         = 1
    fields        = ("tipo", "monto", "descripcion", "pedido")
    readonly_fields = ("fecha",)


@admin.register(CajaDiaria)
class CajaDiariaAdmin(admin.ModelAdmin):
    list_display    = ("fecha", "monto_inicial", "monto_cierre_esperado",
                       "monto_cierre_real", "diferencia_badge", "cerrada")
    list_filter     = ("cerrada",)
    readonly_fields = ("monto_cierre_esperado", "diferencia", "abierta_en", "cerrada_en")
    inlines         = [MovimientoCajaInline]

    def diferencia_badge(self, obj):
        if obj.diferencia is None:
            return "–"
        color = "#1D9E75" if obj.diferencia >= 0 else "#E24B4A"
        signo = "+" if obj.diferencia >= 0 else ""
        return format_html(
            '<span style="color:{};font-weight:bold">{}{}</span>',
            color, signo, obj.diferencia
        )
    diferencia_badge.short_description = "Diferencia"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.calcular_cierre_esperado()
        obj.save(update_fields=["monto_cierre_esperado"])


@admin.register(AjusteStock)
class AjusteStockAdmin(admin.ModelAdmin):
    list_display  = ("sabor", "cantidad_kg", "motivo", "fecha")
    list_filter   = ("sabor",)
    readonly_fields = ("fecha",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.aplicar()


@admin.register(InsumoStock)
class InsumoStockAdmin(admin.ModelAdmin):
    list_display  = ("nombre", "unidad", "cantidad_actual", "cantidad_minima", "alerta_stock")
    list_editable = ("cantidad_actual",)

    def alerta_stock(self, obj):
        if obj.bajo_stock:
            return format_html('<span style="color:#E24B4A;font-weight:bold">⚠ Bajo stock</span>')
        return format_html('<span style="color:#1D9E75">✔ OK</span>')
    alerta_stock.short_description = "Alerta"