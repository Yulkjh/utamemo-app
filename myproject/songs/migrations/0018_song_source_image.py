# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('songs', '0017_add_total_plays'),
    ]

    operations = [
        migrations.AddField(
            model_name='song',
            name='source_image',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='songs',
                to='songs.uploadedimage',
                verbose_name='元画像'
            ),
        ),
    ]
