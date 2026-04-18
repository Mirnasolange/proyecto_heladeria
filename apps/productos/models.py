from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal


class Sabor(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    stock_kg = models.DecimalField(
        max_digits=8, decimal_places=3, default=0,
        validators=[MinValueValidator(Decimal('0'))]
    )
    stock_minimo_kg = models.DecimalField(
        max_digits=8, decimal_places=3, default=Decimal('0.5'),
        help_text="Si el stock cae por debajo de este valor, se muestra como agotado en la web."
    )
    activo = models.BooleanField(default=True)
    

    @property
    def disponible(self):
        return self.activo and self.stock_kg >= self.stock_minimo_kg

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name = "Sabor"
        verbose_name_plural = "Sabores"
        ordering = ["nombre"]


class Topping(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    precio_extra = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('100.00'),
        help_text="Precio adicional a partir del segundo topping."
    )
    activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name = "Topping"
        verbose_name_plural = "Toppings"
        ordering = ["nombre"]


class Producto(models.Model):
    TIPO_HELADO_CUARTO = "helado_cuarto"
    TIPO_HELADO_MEDIO  = "helado_medio"
    TIPO_HELADO_KILO   = "helado_kilo"
    TIPO_POSTRE        = "postre"

    TIPO_CHOICES = [
        (TIPO_HELADO_CUARTO, "Helado 1/4 kg"),
        (TIPO_HELADO_MEDIO,  "Helado 1/2 kg"),
        (TIPO_HELADO_KILO,   "Helado 1 kg"),
        (TIPO_POSTRE,        "Postre"),
    ]

    LIMITE_SABORES = {
        TIPO_HELADO_CUARTO: 3,
        TIPO_HELADO_MEDIO:  4,
        TIPO_HELADO_KILO:   4,
    }

    nombre      = models.CharField(max_length=150)
    tipo        = models.CharField(max_length=20, choices=TIPO_CHOICES)
    precio      = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    descripcion = models.TextField(blank=True)
    activo      = models.BooleanField(default=True)

    @property
    def es_helado(self):
        return self.tipo in [self.TIPO_HELADO_CUARTO, self.TIPO_HELADO_MEDIO, self.TIPO_HELADO_KILO]

    @property
    def limite_sabores(self):
        return self.LIMITE_SABORES.get(self.tipo, 0)

    @property
    def peso_kg(self):
        pesos = {
            self.TIPO_HELADO_CUARTO: Decimal('0.25'),
            self.TIPO_HELADO_MEDIO:  Decimal('0.5'),
            self.TIPO_HELADO_KILO:   Decimal('1.0'),
        }
        return pesos.get(self.tipo, Decimal('0'))

    def __str__(self):
        return f"{self.nombre} ({self.get_tipo_display()})"

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        ordering = ["tipo", "nombre"]