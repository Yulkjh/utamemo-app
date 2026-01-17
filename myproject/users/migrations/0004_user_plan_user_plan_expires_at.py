# Generated migration for adding plan fields to User model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_user_encryption_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='plan',
            field=models.CharField(choices=[('free', 'Free'), ('pro', 'Pro')], default='free', max_length=20, verbose_name='プラン'),
        ),
        migrations.AddField(
            model_name='user',
            name='plan_expires_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='プラン有効期限'),
        ),
    ]
