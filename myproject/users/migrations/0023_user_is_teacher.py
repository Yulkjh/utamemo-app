from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0022_remove_bulk_reviews'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_teacher',
            field=models.BooleanField(
                default=False,
                help_text='運営が付与する先生向けクラス管理権限',
                verbose_name='先生権限',
            ),
        ),
    ]
