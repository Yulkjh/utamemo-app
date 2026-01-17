# Generated manually for Stripe integration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_user_plan_user_plan_expires_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='stripe_customer_id',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='Stripe顧客ID'),
        ),
        migrations.AddField(
            model_name='user',
            name='stripe_subscription_id',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='StripeサブスクリプションID'),
        ),
    ]
