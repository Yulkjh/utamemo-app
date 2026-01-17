# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_user_stripe_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='profile_image_data',
            field=models.TextField(blank=True, null=True, verbose_name='プロフィール画像データ（Base64）'),
        ),
    ]
