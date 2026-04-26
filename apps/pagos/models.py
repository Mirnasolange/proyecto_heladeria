from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal
from django.db.models import Sum
from django.conf import settings

from apps.pedidos.models import Pedido
from apps.productos.models import Sabor


class Pago(models.Model):
    # Tipos principales
    TIPO_EFECTIVO = "EFECTIVO"
    TIPO_TARJETA  = "TARJETA"
    TIPO_DIGITAL  = "DIGITAL"
    TIPO_CHOICES  = [
        (TIPO_EFECTIVO, "Efectivo"),
        (TIPO_TARJETA,  "Tarjeta"),
        (TIPO_DIGITAL,  "Digital"),
    ]

    # Subtipos — solo aplican según el tipo principal
    SUBTIPO_DEBITO       = "DEBITO"
    SUBTIPO_CREDITO      = "CREDITO"
    SUBTIPO_MERCADOPAGO  = "MERCADOPAGO"
    SUBTIPO_TRANSFERENCIA= "TRANSFERENCIA"
    SUBTIPO_CHOICES = [
        (SUBTIPO_DEBITO,        "Débito"),
        (SUBTIPO_CREDITO,       "Crédito"),
        (SUBTIPO_MERCADOPAGO,   "MercadoPago"),
        (SUBTIPO_TRANSFERENCIA, "Transferencia"),
    ]

    # Mapa tipo → subtipos válidos (usado en validación y frontend)
    SUBTIPOS_POR_TIPO = {
        TIPO_TARJETA: [SUBTIPO_DEBITO, SUBTIPO_CREDITO],
        TIPO_DIGITAL: [SUBTIPO_MERCADOPAGO, SUBTIPO_TRANSFERENCIA],
    }

    ESTADO_PENDIENTE = "PENDIENTE"
    ESTADO_APROBADO  = "APROBADO"
    ESTADO_RECHAZADO = "RECHAZADO"
    ESTADO_CHOICES   = [
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_APROBADO,  "Aprobado"),
        (ESTADO_RECHAZADO, "Rechazado"),
    ]

    pedido    = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="pagos")
    tipo      = models.CharField(max_length=15, choices=TIPO_CHOICES)
    subtipo   = models.CharField(max_length=20, choices=SUBTIPO_CHOICES, blank=True, default="")
    monto     = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))]
    )
    estado    = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=ESTADO_APROBADO)
    referencia= models.CharField(
        max_length=200, blank=True,
        help_text="Nro. de comprobante, ID de transacción MP, etc. No aplica a efectivo."
    )
    fecha     = models.DateTimeField(auto_now_add=True)

    @property
    def es_efectivo(self):
        return self.tipo == self.TIPO_EFECTIVO

    @property
    def es_digital(self):
        return self.tipo == self.TIPO_DIGITAL

    @property
    def label_completo(self):
        """Ej: 'Tarjeta – Débito', 'Digital – MercadoPago', 'Efectivo'"""
        if self.subtipo:
            return f"{self.get_tipo_display()} – {self.get_subtipo_display()}"
        return self.get_tipo_display()

    def __str__(self):
        return f"{self.label_completo} ${self.monto} ({self.get_estado_display()}) – {self.pedido.numero}"

    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ["-fecha"]


class CajaDiaria(models.Model):
    fecha                 = models.DateField(unique=True)
    monto_inicial         = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    monto_cierre_esperado = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    monto_cierre_real     = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    diferencia            = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cerrada               = models.BooleanField(default=False)
    abierta_en            = models.DateTimeField(auto_now_add=True)
    cerrada_en            = models.DateTimeField(null=True, blank=True)

    def calcular_cierre_esperado(self):
        ingresos = (
            self.movimientos.filter(tipo=MovimientoCaja.TIPO_INGRESO)
            .aggregate(Sum("monto"))["monto__sum"] or Decimal("0")
        )
        egresos = (
            self.movimientos.filter(tipo=MovimientoCaja.TIPO_EGRESO)
            .aggregate(Sum("monto"))["monto__sum"] or Decimal("0")
        )
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
    pedido      = models.ForeignKey(
        Pedido, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="movimientos_caja"
    )
    tipo        = models.CharField(max_length=8, choices=TIPO_CHOICES)
    monto       = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))]
    )
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
    cantidad_kg = models.DecimalField(
        max_digits=8, decimal_places=3,
        help_text="Positivo = suma. Negativo = resta."
    )
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
    UNIDAD_UNIDAD  = "unidad"
    UNIDAD_PAQUETE = "paquete"
    UNIDAD_CHOICES = [
        (UNIDAD_UNIDAD,  "Unidad"),
        (UNIDAD_PAQUETE, "Paquete"),
    ]

    nombre          = models.CharField(max_length=100, unique=True)
    unidad          = models.CharField(max_length=15, choices=UNIDAD_CHOICES, default=UNIDAD_UNIDAD)
    cantidad_actual = models.PositiveIntegerField(default=0)
    cantidad_minima = models.PositiveIntegerField(default=10)

    @property
    def bajo_stock(self):
        return self.cantidad_actual <= self.cantidad_minima

    def descontar(self, cantidad=1):
        self.cantidad_actual = max(0, self.cantidad_actual - cantidad)
        self.save(update_fields=["cantidad_actual"])

    def __str__(self):
        return f"{self.nombre} ({self.cantidad_actual} {self.get_unidad_display()})"

    class Meta:
        verbose_name = "Insumo"
        verbose_name_plural = "Insumos"
        ordering = ["nombre"]


#────────────────────────────────────────────────────────────────────────
#────────────────────────────────────────────────────────────────────────
#────────────────────────────────────────────────────────────────────────
#────────────────────────────────────────────────────────────────────────
#────────────────────────────────────────────────────────────────────────

# ── NUEVOS modelos al final del archivo (no borrar nada existente) ──

class Caja(models.Model):
    nombre     = models.CharField(max_length=100, unique=True)
    descripcion= models.CharField(max_length=255, blank=True)
    activa     = models.BooleanField(default=True)
    creada_en  = models.DateTimeField(auto_now_add=True)

    def sesion_abierta(self):
        return self.sesiones.filter(estado=CajaSesion.ESTADO_ABIERTA).first()

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name = "Caja"
        verbose_name_plural = "Cajas"
        ordering = ["nombre"]


class CajaSesion(models.Model):
    ESTADO_ABIERTA = "ABIERTA"
    ESTADO_CERRADA = "CERRADA"
    ESTADO_CHOICES = [
        (ESTADO_ABIERTA, "Abierta"),
        (ESTADO_CERRADA, "Cerrada"),
    ]

    caja              = models.ForeignKey(Caja, on_delete=models.PROTECT, related_name="sesiones")
    usuario_apertura  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="sesiones_apertura"
    )
    usuario_cierre    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="sesiones_cierre"
    )
    fecha_apertura    = models.DateTimeField(default=timezone.now)
    fecha_cierre      = models.DateTimeField(null=True, blank=True)
    monto_inicial     = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    efectivo_real     = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    efectivo_esperado = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    diferencia        = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    estado            = models.CharField(max_length=8, choices=ESTADO_CHOICES, default=ESTADO_ABIERTA)

    # Opcionales (ya los usaremos en los métodos)
    ingresos_manuales = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    egresos           = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    fondo_fijo_dejado = models.DecimalField(max_digits=12, decimal_places=2,null=True, blank=True,
    help_text="Monto de efectivo dejado para la siguiente sesión al cerrar.")

    # ── Métodos de negocio ──────────────────────────────────────────

    def calcular_efectivo_esperado(self):
        """
        efectivo_esperado = monto_inicial
                          + ventas en efectivo de esta sesión
                          + ingresos manuales
                          - egresos
        NUNCA confiar en el frontend: siempre recalcular desde BD.
        """
        from django.db.models import Sum as DSum
        ventas_ef = (
            Pago.objects
            .filter(
                pedido__movimientos_sesion__sesion=self,
                tipo=Pago.TIPO_EFECTIVO,
                estado=Pago.ESTADO_APROBADO,
            )
            .aggregate(total=DSum("monto"))["total"] or Decimal("0")
        )

        # ingresos/egresos manuales de esta sesión
        ing = (
            MovimientoCajaSesion.objects
            .filter(sesion=self, tipo=MovimientoCajaSesion.TIPO_INGRESO)
            .aggregate(total=DSum("monto"))["total"] or Decimal("0")
        )
        egr = (
            MovimientoCajaSesion.objects
            .filter(sesion=self, tipo=MovimientoCajaSesion.TIPO_EGRESO)
            .aggregate(total=DSum("monto"))["total"] or Decimal("0")
        )
        self.ingresos_manuales = ing
        self.egresos = egr
        self.efectivo_esperado = self.monto_inicial + ventas_ef + ing - egr
        return self.efectivo_esperado

    def cerrar(self, efectivo_real, usuario):
        """
        Cierra la sesión de forma atómica.
        Lanza ValueError si ya está cerrada.
        """
        from django.db import transaction

        if self.estado == self.ESTADO_CERRADA:
            raise ValueError("Esta sesión ya fue cerrada.")

        with transaction.atomic():
            self.calcular_efectivo_esperado()
            self.efectivo_real   = Decimal(str(efectivo_real))
            self.diferencia      = self.efectivo_real - self.efectivo_esperado
            self.estado          = self.ESTADO_CERRADA
            self.usuario_cierre  = usuario
            self.fecha_cierre    = timezone.now()
            self.save()

    def datos_corte(self):
        """
        Devuelve dict con todo lo necesario para el modal de cierre.
        Siempre calculado desde BD.
        """
        from django.db.models import Sum as DSum

        # Ventas desagregadas por tipo de pago
        pagos_qs = (
            Pago.objects
            .filter(
                pedido__movimientos_sesion__sesion=self,
                estado=Pago.ESTADO_APROBADO,
            )
        )
        ventas_ef  = pagos_qs.filter(tipo=Pago.TIPO_EFECTIVO).aggregate(t=DSum("monto"))["t"] or Decimal("0")
        ventas_tar = pagos_qs.filter(tipo=Pago.TIPO_TARJETA).aggregate(t=DSum("monto"))["t"]  or Decimal("0")
        ventas_dig = pagos_qs.filter(tipo=Pago.TIPO_DIGITAL).aggregate(t=DSum("monto"))["t"]  or Decimal("0")

        ing = (
            MovimientoCajaSesion.objects
            .filter(sesion=self, tipo=MovimientoCajaSesion.TIPO_INGRESO)
            .aggregate(t=DSum("monto"))["t"] or Decimal("0")
        )
        egr = (
            MovimientoCajaSesion.objects
            .filter(sesion=self, tipo=MovimientoCajaSesion.TIPO_EGRESO)
            .aggregate(t=DSum("monto"))["t"] or Decimal("0")
        )
        ef_esperado = self.monto_inicial + ventas_ef + ing - egr

        return {
            "monto_inicial":    float(self.monto_inicial),
            "ventas_efectivo":  float(ventas_ef),
            "ventas_tarjeta":   float(ventas_tar),
            "ventas_digital":   float(ventas_dig),
            "ingresos_manuales":float(ing),
            "egresos":          float(egr),
            "efectivo_esperado":float(ef_esperado),
        }

    def __str__(self):
        return f"{self.caja} | {self.fecha_apertura.strftime('%d/%m/%Y %H:%M')} [{self.estado}]"

    class Meta:
        verbose_name = "Sesión de caja"
        verbose_name_plural = "Sesiones de caja"
        ordering = ["-fecha_apertura"]
        # Garantiza unicidad a nivel de BD: solo una sesión ABIERTA por caja
        constraints = [
            models.UniqueConstraint(
                fields=["caja"],
                condition=models.Q(estado="ABIERTA"),
                name="unique_sesion_abierta_por_caja",
            )
        ]


class MovimientoCajaSesion(models.Model):
    """
    Movimientos ligados a una CajaSesion (nueva lógica).
    Reemplaza gradualmente a MovimientoCaja para el flujo POS.
    """
    TIPO_INGRESO = "INGRESO"
    TIPO_EGRESO  = "EGRESO"
    TIPO_CHOICES = [
        (TIPO_INGRESO, "Ingreso"),
        (TIPO_EGRESO,  "Egreso"),
    ]

    sesion      = models.ForeignKey(CajaSesion, on_delete=models.CASCADE, related_name="movimientos_sesion")
    pedido      = models.ForeignKey(
        "pedidos.Pedido", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="movimientos_sesion"
    )
    tipo        = models.CharField(max_length=8, choices=TIPO_CHOICES)
    monto       = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))]
    )
    descripcion = models.CharField(max_length=255, blank=True)
    fecha       = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_tipo_display()} ${self.monto} – {self.descripcion or self.fecha.strftime('%H:%M')}"

    class Meta:
        verbose_name = "Movimiento de sesión"
        verbose_name_plural = "Movimientos de sesión"
        ordering = ["-fecha"]