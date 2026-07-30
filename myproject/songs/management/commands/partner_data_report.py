"""
外部データ提供元（DataPartner）向けの利用状況レポートを表示するコマンド

覚書等の「データの活用状況を報告する」義務（第5条相当）に応えるための、
そのまま提供元への報告に使える利用状況サマリを表示する（読み取り専用）。

使い方:
  python manage.py partner_data_report clearnote
"""
from django.core.management.base import BaseCommand, CommandError

from songs.models import DataPartner, TrainingData, PartnerDataAccessLog


class Command(BaseCommand):
    help = 'DataPartner の利用状況レポートを表示する（第5条: 成果報告用、読み取り専用）'

    def add_arguments(self, parser):
        parser.add_argument('partner_slug', help='レポート対象の DataPartner の slug')

    def handle(self, *args, **options):
        try:
            partner = DataPartner.objects.get(slug=options['partner_slug'])
        except DataPartner.DoesNotExist:
            raise CommandError(f'DataPartner "{options["partner_slug"]}" が見つかりません。')

        qs = TrainingData.objects.filter(data_partner=partner).order_by('created_at')
        count = qs.count()

        self.stdout.write('=' * 60)
        self.stdout.write(f'データ提供元レポート: {partner.name} ({partner.slug})')
        self.stdout.write('=' * 60)
        self.stdout.write(f'契約参照: {partner.contract_reference or "(未記入)"}')
        self.stdout.write(f'許諾範囲: {partner.permitted_scope or "(未記入)"}')
        self.stdout.write(f'状態: {"有効" if partner.is_active else "無効（削除済み/契約終了）"}')
        if partner.deletion_requested_at:
            self.stdout.write(f'削除依頼受領日時: {partner.deletion_requested_at}')
        self.stdout.write('')

        authorized = list(partner.authorized_users.all().values_list('username', flat=True))
        self.stdout.write(f'現在の取扱許可メンバー ({len(authorized)}名): {", ".join(authorized) or "(なし)"}')
        self.stdout.write('')

        self.stdout.write(f'現在DBに存在するデータ件数: {count} 件')
        if count:
            first = qs.first()
            last = qs.last()
            self.stdout.write(f'  最初のインポート日時: {first.created_at}')
            self.stdout.write(f'  最新のインポート日時: {last.created_at}')
        self.stdout.write('')

        logs = PartnerDataAccessLog.objects.filter(data_partner=partner).order_by('created_at')
        self.stdout.write(f'アクセス履歴 ({logs.count()} 件):')
        if not logs.exists():
            self.stdout.write('  (履歴なし)')
        for log in logs:
            actor = log.user.username if log.user else (
                log.training_session.machine_name if log.training_session else '(不明)'
            )
            self.stdout.write(
                f'  [{log.created_at:%Y-%m-%d %H:%M}] {log.get_action_display()} '
                f'{log.record_count}件 by {actor} - {log.detail}'
            )
