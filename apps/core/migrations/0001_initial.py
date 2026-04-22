from django.db import migrations
from django.contrib.auth.models import User

def create_admin(apps, schema_editor):
    if not User.objects.filter(username="admin").exists():
        User.objects.create_superuser(
            username="admin",
            email="admin@admin.com",
            password="admin123"
        )

class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(create_admin),
    ]