from django.contrib import admin
from django.utils.html import format_html
from .models import Sabor, Topping, Producto


@admin.register(Sabor)
class SaborAdmin(admin.ModelAdmin):
    list_display  = ("nombre", "stock_kg", "stock_minimo_kg", "estado_stock", "activo")
    list_filter   = ("activo",)
    search_fields = ("nombre",)
    list_editable = ("activo",)

    def estado_stock(self, obj):
        if obj.activo and obj.stock_kg >= obj.stock_minimo_kg:
            return format_html('<span style="color:green;font-weight:bold">✔ Disponible</span>')
        return format_html('<span style="color:red;font-weight:bold">✘ Agotado</span>')
    estado_stock.short_description = "Estado"


@admin.register(Topping)
class ToppingAdmin(admin.ModelAdmin):
    list_display  = ("nombre", "precio_extra", "activo")
    list_editable = ("activo", "precio_extra")


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display  = ("nombre", "tipo", "precio", "activo")
    list_filter   = ("tipo", "activo")
    search_fields = ("nombre",)
    list_editable = ("precio", "activo")