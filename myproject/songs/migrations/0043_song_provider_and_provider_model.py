from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('songs', '0042_classroomassignment'),
    ]

    operations = [
        migrations.AddField(
            model_name='song',
            name='provider_model',
            field=models.CharField(blank=True, default='mureka-v8', help_text='プロバイダごとの実際のモデル名', max_length=100, verbose_name='プロバイダモデル'),
        ),
        migrations.AddField(
            model_name='song',
            name='song_provider',
            field=models.CharField(choices=[('mureka', 'Mureka'), ('lyria', 'Lyria')], default='mureka', help_text='楽曲生成に使用するAIプロバイダ', max_length=20, verbose_name='楽曲生成プロバイダ'),
        ),
    ]