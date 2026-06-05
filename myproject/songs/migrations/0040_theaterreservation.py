from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('songs', '0039_add_indexes_like_favorite_comment_playhistory'),
    ]

    operations = [
        migrations.CreateModel(
            name='TheaterReservation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('show_key', models.CharField(max_length=80, verbose_name='上映キー')),
                ('show_title', models.CharField(max_length=200, verbose_name='上映作品')),
                ('show_time', models.CharField(max_length=20, verbose_name='上映時間')),
                ('seat_id', models.CharField(max_length=10, verbose_name='座席番号')),
                ('guest_name', models.CharField(max_length=80, verbose_name='予約名')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='予約日時')),
            ],
            options={
                'verbose_name': '劇場予約',
                'verbose_name_plural': '劇場予約',
                'ordering': ['show_key', 'seat_id'],
                'constraints': [models.UniqueConstraint(fields=('show_key', 'seat_id'), name='unique_theater_reservation_seat')],
            },
        ),
    ]