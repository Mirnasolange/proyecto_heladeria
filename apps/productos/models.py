from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal


class Sabor(models.Model):
    nombre           = models.CharField(max_length=100, unique=True)
    stock_kg         = models.DecimalField(max_digits=8, decimal_places=3, default=0,
                           validators=[MinValueValidator(Decimal('0'))])
    stock_minimo_kg  = models.DecimalField(max_digits=8, decimal_places=3, default=Decimal('0.5'))
    activo           = models.BooleanField(default=True)

    @property
    def disponible(self):
        return self.activo and self.stock_kg >= self.stock_minimo_kg

    def __str__(self): return self.nombre

    class Meta:
        verbose_name = "Sabor"; verbose_name_plural = "Sabores"; ordering = ["nombre"]


class Topping(models.Model):
    nombre       = models.CharField(max_length=100, unique=True)
    precio_extra = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('100.00'))
    activo       = models.BooleanField(default=True)

    def __str__(self): return self.nombre

    class Meta:
        verbose_name = "Topping"; verbose_name_plural = "Toppings"; ordering = ["nombre"]


class InsumoStock(models.Model):
    UNIDAD_UNIDAD  = "unidad"
    UNIDAD_PAQUETE = "paquete"
    UNIDAD_CHOICES = [(UNIDAD_UNIDAD, "Unidad"), (UNIDAD_PAQUETE, "Paquete")]

    nombre          = models.CharField(max_length=100, unique=True)
    unidad          = models.CharField(max_length=15, choices=UNIDAD_CHOICES, default=UNIDAD_UNIDAD)
    cantidad_actual = models.PositiveIntegerField(default=0)
    cantidad_minima = models.PositiveIntegerField(default=10)

    @property
    def bajo_stock(self): return self.cantidad_actual <= self.cantidad_minima

    def descontar(self, cantidad=1):
        self.cantidad_actual = max(0, self.cantidad_actual - cantidad)
        self.save(update_fields=["cantidad_actual"])

    def __str__(self): return f"{self.nombre} ({self.cantidad_actual} {self.get_unidad_display()})"

    class Meta:
        verbose_name = "Insumo"; verbose_name_plural = "Insumos"; ordering = ["nombre"]


class Producto(models.Model):
    # Tipos — cada tamaño de helado es un producto independiente
    TIPO_HELADO_CUARTO = "helado_cuarto"
    TIPO_HELADO_MEDIO  = "helado_medio"
    TIPO_HELADO_KILO   = "helado_kilo"
    TIPO_POSTRE        = "postre"
    TIPO_OTRO          = "otro"

    TIPO_CHOICES = [
        (TIPO_HELADO_CUARTO, "Helado 1/4 kg"),
        (TIPO_HELADO_MEDIO,  "Helado 1/2 kg"),
        (TIPO_HELADO_KILO,   "Helado 1 kg"),
        (TIPO_POSTRE,        "Postre"),
        (TIPO_OTRO,          "Otro"),
    ]

    LIMITE_SABORES = {
        TIPO_HELADO_CUARTO: 3,
        TIPO_HELADO_MEDIO:  4,
        TIPO_HELADO_KILO:   4,
    }

    PESO_KG = {
        TIPO_HELADO_CUARTO: Decimal('0.25'),
        TIPO_HELADO_MEDIO:  Decimal('0.5'),
        TIPO_HELADO_KILO:   Decimal('1.0'),
    }

    nombre           = models.CharField(max_length=150)
    tipo             = models.CharField(max_length=20, choices=TIPO_CHOICES)
    precio           = models.DecimalField(max_digits=10, decimal_places=2,
                           validators=[MinValueValidator(Decimal('0'))])
    descripcion      = models.TextField(blank=True)
    activo           = models.BooleanField(default=True)

    # Stock propio del producto (unidades, no kg)
    tiene_stock      = models.BooleanField(default=False,
                           help_text="Si está activo, se controla el stock de unidades.")
    stock_unidades   = models.PositiveIntegerField(default=0)
    stock_minimo_u   = models.PositiveIntegerField(default=5)

    # Insumo que se descuenta automáticamente con cada venta (ej: térmico)
    insumo_asociado  = models.ForeignKey(
        InsumoStock, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="productos",
        help_text="Insumo que se descuenta 1 unidad por cada ítem vendido (ej: térmico 1/4)."
    )

    @property
    def es_helado(self):
        return self.tipo in [self.TIPO_HELADO_CUARTO, self.TIPO_HELADO_MEDIO, self.TIPO_HELADO_KILO]

    @property
    def limite_sabores(self):
        return self.LIMITE_SABORES.get(self.tipo, 0)

    @property
    def peso_kg(self):
        return self.PESO_KG.get(self.tipo, Decimal('0'))

    @property
    def disponible(self):
        if self.tiene_stock:
            return self.activo and self.stock_unidades >= self.stock_minimo_u
        return self.activo

    def descontar_stock(self, cantidad=1):
        """Descuenta stock del producto e insumo asociado."""
        if self.tiene_stock:
            self.stock_unidades = max(0, self.stock_unidades - cantidad)
            self.save(update_fields=["stock_unidades"])
        if self.insumo_asociado:
            self.insumo_asociado.descontar(cantidad)

    def __str__(self):
        return f"{self.nombre} ({self.get_tipo_display()})"

    class Meta:
        verbose_name = "Producto"; verbose_name_plural = "Productos"
        ordering = ["tipo", "nombre"]