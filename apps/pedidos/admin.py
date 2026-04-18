from django.contrib import admin
from django.utils.html import format_html
from .models import Pedido, ItemPedido, ItemPedidoSabor, ItemPedidoTopping


class ItemPedidoSaborInline(admin.TabularInline):
    model  = ItemPedidoSabor
    extra  = 0
    fields = ("sabor", "orden")


class ItemPedidoToppingInline(admin.TabularInline):
    model  = ItemPedidoTopping
    extra  = 0
    fields = ("topping",)


class ItemPedidoInline(admin.StackedInline):
    model       = ItemPedido
    extra       = 0
    fields      = ("producto", "cantidad", "precio_unitario", "subtotal", "comentarios")
    readonly_fields = ("subtotal",)
    show_change_link = True


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display   = ("numero", "cliente_nombre", "cliente_telefono", "tipo_pedido",
                      "tipo_entrega", "estado_badge", "metodo_pago_principal", "total", "fecha_creacion")
    list_filter    = ("estado", "tipo_pedido", "tipo_entrega", "metodo_pago_principal")
    search_fields  = ("numero", "cliente_nombre", "cliente_telefono")
    readonly_fields = ("numero", "fecha_creacion", "fecha_actualizacion")
    inlines        = [ItemPedidoInline]
    list_per_page  = 30

    COLORES_ESTADO = {
        "RECIBIDO":       "#3B8BD4",
        "EN_PREPARACION": "#EF9F27",
        "LISTO":          "#1D9E75",
        "EN_CAMINO":      "#534AB7",
        "ENTREGADO":      "#888780",
        "CANCELADO":      "#E24B4A",
    }

    def estado_badge(self, obj):
        color = self.COLORES_ESTADO.get(obj.estado, "#888")
        return format_html(
            '<span style="background:{};color:#fff;padding:3px 10px;border-radius:12px;font-size:12px">{}</span>',
            color, obj.get_estado_display()
        )
    estado_badge.short_description = "Estado"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.calcular_total()


@admin.register(ItemPedido)
class ItemPedidoAdmin(admin.ModelAdmin):
    list_display = ("pedido", "producto", "cantidad", "precio_unitario", "subtotal")
    inlines      = [ItemPedidoSaborInline, ItemPedidoToppingInline]