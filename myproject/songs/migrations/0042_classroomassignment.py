from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('songs', '0041_theatersurveyresponse_prompttemplate_user_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ClassroomAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('due_date', models.DateField(blank=True, null=True, verbose_name='期限日')),
                ('note', models.TextField(blank=True, verbose_name='課題メモ')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='作成日時')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新日時')),
                ('assigned_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assigned_classroom_tasks', to=settings.AUTH_USER_MODEL, verbose_name='出題者')),
                ('classroom', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='songs.classroom', verbose_name='クラス')),
                ('song', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='classroom_assignments', to='songs.song', verbose_name='課題曲')),
            ],
            options={
                'verbose_name': 'クラス課題',
                'verbose_name_plural': 'クラス課題',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='classroomassignment',
            constraint=models.UniqueConstraint(fields=('classroom', 'song'), name='unique_classroom_assignment_song'),
        ),
    ]
