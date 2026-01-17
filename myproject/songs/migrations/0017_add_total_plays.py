# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('songs', '0016_add_reference_audio_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='song',
            name='total_plays',
            field=models.PositiveIntegerField(default=0, verbose_name='総再生回数'),
        ),
    ]
