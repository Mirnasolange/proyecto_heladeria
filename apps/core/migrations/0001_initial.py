from django.db import migrations

def create_admin(apps, schema_editor):
    User = apps.get_model("auth", "User")

    if not User.objects.filter(username="admin").exists():
        User.objects.create_superuser(
            username="admin",
            email="admin@admin.com",
            password="admin123"
        )

class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_admin),
    ]