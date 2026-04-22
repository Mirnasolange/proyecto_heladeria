import json
from django.apps import apps

def load_fixture():
    with open("productos/fixtures/datos_prueba.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    for obj in data:
        model_label = obj["model"]  # ej: productos.producto
        pk = obj["pk"]
        fields = obj["fields"]

        Model = apps.get_model(model_label)

        # 🔍 evitar duplicados por PK (lo más seguro)
        obj_db, created = Model.objects.update_or_create(
            pk=pk,
            defaults=fields
        )