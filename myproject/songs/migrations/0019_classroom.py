# Generated manually

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('songs', '0018_song_source_image'),
    ]

    operations = [
        migrations.CreateModel(
            name='Classroom',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='クラス名')),
                ('code', models.CharField(help_text='生徒が参加するためのコード', max_length=8, unique=True, verbose_name='参加コード')),
                ('description', models.TextField(blank=True, verbose_name='説明')),
                ('is_active', models.BooleanField(default=True, verbose_name='アクティブ')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='作成日時')),
                ('host', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hosted_classrooms', to=settings.AUTH_USER_MODEL, verbose_name='ホスト（先生）')),
            ],
            options={
                'verbose_name': 'クラス',
                'verbose_name_plural': 'クラス',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ClassroomMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('joined_at', models.DateTimeField(auto_now_add=True, verbose_name='参加日時')),
                ('classroom', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='songs.classroom', verbose_name='クラス')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='ユーザー')),
            ],
            options={
                'verbose_name': 'クラスメンバーシップ',
                'verbose_name_plural': 'クラスメンバーシップ',
                'unique_together': {('user', 'classroom')},
            },
        ),
        migrations.AddField(
            model_name='classroom',
            name='members',
            field=models.ManyToManyField(related_name='joined_classrooms', through='songs.ClassroomMembership', to=settings.AUTH_USER_MODEL, verbose_name='メンバー'),
        ),
        migrations.CreateModel(
            name='ClassroomSong',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('shared_at', models.DateTimeField(auto_now_add=True, verbose_name='共有日時')),
                ('classroom', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shared_songs', to='songs.classroom', verbose_name='クラス')),
                ('shared_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='共有者')),
                ('song', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='classroom_shares', to='songs.song', verbose_name='楽曲')),
            ],
            options={
                'verbose_name': 'クラス共有楽曲',
                'verbose_name_plural': 'クラス共有楽曲',
                'ordering': ['-shared_at'],
                'unique_together': {('classroom', 'song')},
            },
        ),
    ]
