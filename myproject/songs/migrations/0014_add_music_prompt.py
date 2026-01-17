# Generated migration for adding music_prompt field to Song model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('songs', '0013_add_mureka_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='song',
            name='music_prompt',
            field=models.TextField(
                blank=True, 
                null=True, 
                verbose_name='音楽スタイルプロンプト',
                help_text='ユーザーが指定した音楽スタイルの詳細指示'
            ),
        ),
    ]
