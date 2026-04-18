from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal

from apps.pedidos.models import Pedido
from apps.productos.models import Sabor


class Pago(models.Model):
    TIPO_EFECTIVO = "EFECTIVO"
    TIPO_MP       = "MERCADOPAGO"
    TIPO_CHOICES  = [
        (TIPO_EFECTIVO, "Efectivo"),
        (TIPO_MP,       "MercadoPago"),
    ]

    ESTADO_PENDIENTE  = "PENDIENTE"
    ESTADO_APROBADO   = "APROBADO"
    ESTADO_RECHAZADO  = "RECHAZADO"
    ESTADO_CHOICES    = [
        (ESTADO_PENDIENTE,  "Pendiente"),
        (ESTADO_APROBADO,   "Aprobado"),
        (ESTADO_RECHAZADO,  "Rechazado"),
    ]

    pedido             = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="pagos")
    tipo               = models.CharField(max_length=15, choices=TIPO_CHOICES)
    monto              = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    estado             = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    referencia_externa = models.CharField(max_length=200, blank=True, help_text="ID de transacción MP u otra referencia.")
    fecha              = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_tipo_display()} ${self.monto} ({self.get_estado_display()}) – {self.pedido.numero}"

    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ["-fecha"]


class CajaDiaria(models.Model):
    fecha                  = models.DateField(unique=True)
    monto_inicial          = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    monto_cierre_esperado  = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    monto_cierre_real      = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    diferencia             = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cerrada                = models.BooleanField(default=False)
    abierta_en             = models.DateTimeField(auto_now_add=True)
    cerrada_en             = models.DateTimeField(null=True, blank=True)

    def calcular_cierre_esperado(self):
        from django.db.models import Sum
        ingresos = self.movimientos.filter(tipo=MovimientoCaja.TIPO_INGRESO).aggregate(Sum("monto"))["monto__sum"] or Decimal('0')
        egresos  = self.movimientos.filter(tipo=MovimientoCaja.TIPO_EGRESO).aggregate(Sum("monto"))["monto__sum"] or Decimal('0')
        self.monto_cierre_esperado = self.monto_inicial + ingresos - egresos
        return self.monto_cierre_esperado

    def cerrar(self, monto_real):
        self.calcular_cierre_esperado()
        self.monto_cierre_real = monto_real
        self.diferencia        = monto_real - self.monto_cierre_esperado
        self.cerrada           = True
        self.cerrada_en        = timezone.now()
        self.save()

    def __str__(self):
        return f"Caja {self.fecha} – {'Cerrada' if self.cerrada else 'Abierta'}"

    class Meta:
        verbose_name = "Caja diaria"
        verbose_name_plural = "Cajas diarias"
        ordering = ["-fecha"]


class MovimientoCaja(models.Model):
    TIPO_INGRESO = "INGRESO"
    TIPO_EGRESO  = "EGRESO"
    TIPO_CHOICES = [
        (TIPO_INGRESO, "Ingreso"),
        (TIPO_EGRESO,  "Egreso"),
    ]

    caja        = models.ForeignKey(CajaDiaria, on_delete=models.CASCADE, related_name="movimientos")
    pedido      = models.ForeignKey(Pedido, on_delete=models.SET_NULL, null=True, blank=True, related_name="movimientos_caja")
    tipo        = models.CharField(max_length=8, choices=TIPO_CHOICES)
    monto       = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    descripcion = models.CharField(max_length=255, blank=True)
    fecha       = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_tipo_display()} ${self.monto} – {self.descripcion or self.fecha.strftime('%H:%M')}"

    class Meta:
        verbose_name = "Movimiento de caja"
        verbose_name_plural = "Movimientos de caja"
        ordering = ["-fecha"]


class AjusteStock(models.Model):
    sabor       = models.ForeignKey(Sabor, on_delete=models.CASCADE, related_name="ajustes")
    cantidad_kg = models.DecimalField(max_digits=8, decimal_places=3, help_text="Positivo = suma. Negativo = resta.")
    motivo      = models.CharField(max_length=255, blank=True)
    fecha       = models.DateTimeField(auto_now_add=True)

    def aplicar(self):
        self.sabor.stock_kg += self.cantidad_kg
        self.sabor.save(update_fields=["stock_kg"])

    def __str__(self):
        signo = "+" if self.cantidad_kg >= 0 else ""
        return f"{self.sabor.nombre}: {signo}{self.cantidad_kg} kg – {self.fecha.strftime('%d/%m/%Y')}"

    class Meta:
        verbose_name = "Ajuste de stock"
        verbose_name_plural = "Ajustes de stock"
        ordering = ["-fecha"]


class InsumoStock(models.Model):
    UNIDAD_UNIDAD   = "unidad"
    UNIDAD_PAQUETE  = "paquete"
    UNIDAD_CHOICES  = [
        (UNIDAD_UNIDAD,  "Unidad"),
        (UNIDAD_PAQUETE, "Paquete"),
    ]

    nombre           = models.CharField(max_length=100, unique=True)
    unidad           = models.CharField(max_length=15, choices=UNIDAD_CHOICES, default=UNIDAD_UNIDAD)
    cantidad_actual  = models.PositiveIntegerField(default=0)
    cantidad_minima  = models.PositiveIntegerField(default=10)

    @property
    def bajo_stock(self):
        return self.cantidad_actual <= self.cantidad_minima

    def __str__(self):
        return f"{self.nombre} ({self.cantidad_actual} {self.get_unidad_display()})"

    class Meta:
        verbose_name = "Insumo"
        verbose_name_plural = "Insumos"
        ordering = ["nombre"]