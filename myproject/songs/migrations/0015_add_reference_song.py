# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('songs', '0014_add_music_prompt'),
    ]

    operations = [
        migrations.AddField(
            model_name='song',
            name='reference_song',
            field=models.CharField(
                blank=True,
                help_text='参考にしたい曲名（例：YOASOBIの夜に駆ける）',
                max_length=255,
                null=True,
                verbose_name='リファレンス曲'
            ),
        ),
    ]
