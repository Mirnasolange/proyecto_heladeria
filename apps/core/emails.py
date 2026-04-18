from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string


def _enviar(asunto, template, context, destinatario):
    """Helper interno. Nunca explota — loguea el error y sigue."""
    try:
        cuerpo = render_to_string(template, context)
        send_mail(
            subject      = asunto,
            message      = cuerpo,
            from_email   = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@heladeria.com"),
            recipient_list = [destinatario],
            fail_silently  = False,
        )
    except Exception as e:
        # En desarrollo con ConsoleBackend esto imprime en consola.
        # En producción logueá el error correctamente.
        print(f"[EMAIL ERROR] {e}")


def notificar_pedido_recibido(pedido):
    """
    Se llama justo después de crear el pedido en checkout.
    Envía confirmación al cliente Y copia al local.
    """
    context = {"pedido": pedido}

    # Al cliente
    if "@" in pedido.cliente_telefono:   # solo si el teléfono es un email (campo libre)
        _enviar(
            asunto      = f"✅ Pedido {pedido.numero} recibido – Heladería",
            template    = "emails/pedido_recibido.txt",
            context     = context,
            destinatario = pedido.cliente_telefono,
        )

    # Al local (siempre)
    email_local = getattr(settings, "EMAIL_HELADERIA", None)
    if email_local:
        _enviar(
            asunto      = f"🍦 Nuevo pedido {pedido.numero} – {pedido.cliente_nombre}",
            template    = "emails/pedido_nuevo_interno.txt",
            context     = context,
            destinatario = email_local,
        )


def notificar_pedido_listo(pedido):
    """Se llama cuando el estado cambia a LISTO."""
    context = {"pedido": pedido}
    if "@" in pedido.cliente_telefono:
        _enviar(
            asunto      = f"🍦 Tu pedido {pedido.numero} está listo",
            template    = "emails/pedido_listo.txt",
            context     = context,
            destinatario = pedido.cliente_telefono,
        )


def notificar_en_camino(pedido):
    """Se llama cuando el estado cambia a EN_CAMINO."""
    context = {"pedido": pedido}
    if "@" in pedido.cliente_telefono:
        _enviar(
            asunto      = f"🛵 Tu pedido {pedido.numero} está en camino",
            template    = "emails/pedido_en_camino.txt",
            context     = context,
            destinatario = pedido.cliente_telefono,
        )


def notificar_stock_critico(sabores_criticos, insumos_criticos):
    """
    Envía email de alerta de stock al dueño cuando se detectan
    sabores agotados o insumos bajo mínimo.
    """
    from django.conf import settings
 
    email_local = getattr(settings, "EMAIL_HELADERIA", None)
    if not email_local:
        return
 
    lineas = ["⚠️ ALERTA DE STOCK CRÍTICO\n"]
 
    if sabores_criticos:
        lineas.append("Sabores con problemas:")
        for item in sabores_criticos:
            s = item["sabor"]
            lineas.append(f"  • {s.nombre}: {s.stock_kg} kg (mín. {s.stock_minimo_kg} kg)")
 
    if insumos_criticos:
        lineas.append("\nInsumos bajo mínimo:")
        for i in insumos_criticos:
            lineas.append(f"  • {i.nombre}: {i.cantidad_actual} {i.get_unidad_display()} (mín. {i.cantidad_minima})")
 
    lineas.append("\nRevisá el panel de stock.")
    cuerpo = "\n".join(lineas)
 
    _enviar(
        asunto       = "⚠️ Heladería – Stock crítico detectado",
        template     = None,       # usamos cuerpo directo
        context      = {},
        destinatario = email_local,
    )
 
    # Override: enviar con cuerpo directo (sin template)
    from django.core.mail import send_mail
    try:
        send_mail(
            subject        = "⚠️ Heladería – Stock crítico detectado",
            message        = cuerpo,
            from_email     = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@heladeria.com"),
            recipient_list = [email_local],
            fail_silently  = False,
        )
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")

