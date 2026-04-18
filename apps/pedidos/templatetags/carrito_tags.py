from django import template

register = template.Library()

@register.filter
def enumerate_items(lista):
    """
    Uso en template: {% for indice, item in carrito|enumerate_items %}
    Devuelve pares (indice, item) igual que enumerate() de Python.
    """
    return enumerate(lista)