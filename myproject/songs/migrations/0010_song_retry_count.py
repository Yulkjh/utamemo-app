from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('songs', '0009_alter_song_is_encrypted'),
    ]

    operations = [
        migrations.AddField(
            model_name='song',
            name='retry_count',
            field=models.PositiveIntegerField(default=0, verbose_name='再試行回数'),
        ),
    ]
