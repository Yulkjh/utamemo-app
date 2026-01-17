# Generated manually

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('songs', '0010_song_retry_count'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlayHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('play_count', models.PositiveIntegerField(default=0, verbose_name='再生回数')),
                ('last_played_at', models.DateTimeField(auto_now=True, verbose_name='最終再生日時')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='初回再生日時')),
                ('song', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='play_histories', to='songs.song', verbose_name='楽曲')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='play_histories', to=settings.AUTH_USER_MODEL, verbose_name='ユーザー')),
            ],
            options={
                'verbose_name': '再生履歴',
                'verbose_name_plural': '再生履歴',
                'ordering': ['-last_played_at'],
                'unique_together': {('user', 'song')},
            },
        ),
    ]
