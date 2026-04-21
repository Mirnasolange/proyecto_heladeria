from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal

from apps.productos.models import Producto, Sabor, Topping


class Pedido(models.Model):
    TIPO_WEB       = "WEB"
    TIPO_MOSTRADOR = "MOSTRADOR"
    TIPO_CHOICES   = [
        (TIPO_WEB,       "Web"),
        (TIPO_MOSTRADOR, "Mostrador"),
    ]

    ENTREGA_RETIRO  = "RETIRO"
    ENTREGA_DELIVERY = "DELIVERY"
    ENTREGA_CHOICES = [
        (ENTREGA_RETIRO,   "Retiro en local"),
        (ENTREGA_DELIVERY, "Delivery"),
    ]

    ESTADO_RECIBIDO    = "RECIBIDO"
    ESTADO_PREPARACION = "EN_PREPARACION"
    ESTADO_LISTO       = "LISTO"
    ESTADO_EN_CAMINO   = "EN_CAMINO"
    ESTADO_ENTREGADO   = "ENTREGADO"
    ESTADO_CANCELADO   = "CANCELADO"
    ESTADO_CHOICES = [
        (ESTADO_RECIBIDO,    "Recibido"),
        (ESTADO_PREPARACION, "En preparación"),
        (ESTADO_LISTO,       "Listo"),
        (ESTADO_EN_CAMINO,   "En camino"),
        (ESTADO_ENTREGADO,   "Entregado"),
        (ESTADO_CANCELADO,   "Cancelado"),
    ]

    PAGO_EFECTIVO = "EFECTIVO"
    PAGO_MP       = "MERCADOPAGO"
    PAGO_MIXTO    = "MIXTO"
    PAGO_CHOICES  = [
        (PAGO_EFECTIVO, "Efectivo"),
        (PAGO_MP,       "MercadoPago"),
        (PAGO_MIXTO,    "Mixto"),
    ]

    numero                 = models.CharField(max_length=10, unique=True, editable=False)
    cliente_nombre         = models.CharField(max_length=150)
    cliente_telefono       = models.CharField(max_length=30)
    tipo_pedido            = models.CharField(max_length=15, choices=TIPO_CHOICES, default=TIPO_WEB)
    tipo_entrega           = models.CharField(max_length=10, choices=ENTREGA_CHOICES, default=ENTREGA_RETIRO)
    direccion_entrega      = models.CharField(max_length=255, blank=True)
    estado                 = models.CharField(max_length=15, choices=ESTADO_CHOICES, default=ESTADO_RECIBIDO)
    metodo_pago_principal  = models.CharField(max_length=15, choices=PAGO_CHOICES, default=PAGO_EFECTIVO)
    total                  = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    comentarios            = models.TextField(blank=True)
    fecha_creacion         = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion    = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.numero:
            ultimo = Pedido.objects.order_by("-id").first()
            siguiente = (ultimo.id + 1) if ultimo else 1
            self.numero = f"#{siguiente:06d}"
        super().save(*args, **kwargs)

    def calcular_total(self):
        total = sum(item.subtotal for item in self.items.all())
        self.total = total
        self.save(update_fields=["total"])
        return total

    def __str__(self):
        return f"Pedido {self.numero} – {self.cliente_nombre}"

    class Meta:
        verbose_name = "Pedido"
        verbose_name_plural = "Pedidos"
        ordering = ["-fecha_creacion"]


class ItemPedido(models.Model):
    pedido          = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="items")
    producto        = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="items_pedido",null=True, blank=True)
    cantidad        = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    comentarios     = models.TextField(blank=True, help_text="Ej: más chocolate que vainilla, sin toppings, etc.")

    def calcular_subtotal(self):
        precio_base    = self.precio_unitario * self.cantidad
        toppings_count = self.toppings.count()
        precio_toppings = Decimal('0')
        if toppings_count > 1:
            precio_toppings = (toppings_count - 1) * Decimal('100')
        self.subtotal = precio_base + precio_toppings
        return self.subtotal

    def save(self, *args, **kwargs):
        if not self.precio_unitario:
            self.precio_unitario = self.producto.precio
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.cantidad}x {self.producto.nombre} (Pedido {self.pedido.numero})"

    class Meta:
        verbose_name = "Ítem de pedido"
        verbose_name_plural = "Ítems de pedido"


class ItemPedidoSabor(models.Model):
    item_pedido = models.ForeignKey(ItemPedido, on_delete=models.CASCADE, related_name="sabores")
    sabor       = models.ForeignKey(Sabor, on_delete=models.PROTECT, related_name="apariciones")
    orden       = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return f"{self.sabor.nombre} (ítem #{self.item_pedido.id})"

    class Meta:
        verbose_name = "Sabor de ítem"
        verbose_name_plural = "Sabores de ítem"
        ordering = ["orden"]


class ItemPedidoTopping(models.Model):
    item_pedido = models.ForeignKey(ItemPedido, on_delete=models.CASCADE, related_name="toppings")
    topping     = models.ForeignKey(Topping, on_delete=models.PROTECT, related_name="apariciones")

    def __str__(self):
        return f"{self.topping.nombre} (ítem #{self.item_pedido.id})"

    class Meta:
        verbose_name = "Topping de ítem"
        verbose_name_plural = "Toppings de ítem"
        unique_together = [("item_pedido", "topping")]