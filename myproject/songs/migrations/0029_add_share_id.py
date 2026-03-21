"""
Share ID マイグレーション

既存レコードがある場合でも安全に share_id を追加するため、
複数ステップで実行する。

前回のデプロイ失敗で中間状態が残っている場合にも対応。
"""
import secrets
import string

from django.db import connection, migrations, models


def generate_share_id():
    """8文字のランダムな英数字IDを生成"""
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(8))


def add_share_id_column(apps, schema_editor):
    """share_id カラムを安全に追加（既に存在する場合はスキップ）"""
    table_name = 'songs_song'
    column_name = 'share_id'

    columns = [
        col.name for col in connection.introspection.get_table_description(
            connection.cursor(), table_name
        )
    ]
    if column_name in columns:
        return  # 既に存在する

    with connection.cursor() as cursor:
        cursor.execute(
            f'ALTER TABLE {table_name} ADD COLUMN {column_name} varchar(8) NULL'
        )


def populate_share_ids(apps, schema_editor):
    """既存の全Songレコードにユニークな share_id を設定"""
    Song = apps.get_model('songs', 'Song')
    existing_ids = set(
        Song.objects.exclude(share_id__isnull=True)
        .exclude(share_id='')
        .values_list('share_id', flat=True)
    )

    songs_to_update = []
    for song in Song.objects.filter(
        models.Q(share_id__isnull=True) | models.Q(share_id='')
    ).iterator():
        new_id = generate_share_id()
        while new_id in existing_ids:
            new_id = generate_share_id()
        existing_ids.add(new_id)
        song.share_id = new_id
        songs_to_update.append(song)

    if songs_to_update:
        Song.objects.bulk_update(songs_to_update, ['share_id'], batch_size=500)


def cleanup_pg_indexes(apps, schema_editor):
    """PostgreSQL: 前回の失敗デプロイで残った重複インデックスを削除"""
    if connection.vendor != 'postgresql':
        return
    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS songs_song_share_id_be8bd3f1;")
        cursor.execute("DROP INDEX IF EXISTS songs_song_share_id_be8bd3f1_like;")
        # 制約も念のため削除（AlterField が再作成する）
        cursor.execute("""
            DO $$ BEGIN
                ALTER TABLE songs_song DROP CONSTRAINT IF EXISTS songs_song_share_id_key;
            EXCEPTION WHEN undefined_object THEN NULL;
            END $$;
        """)


class Migration(migrations.Migration):

    dependencies = [
        ('songs', '0028_expand_vocal_style_choices'),
    ]

    operations = [
        # Step 1: カラムを安全に追加 (既に存在する場合はスキップ)
        migrations.RunPython(
            add_share_id_column,
            migrations.RunPython.noop,
        ),
        # Django の state を更新 (DB操作はRunPythonで行った)
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='song',
                    name='share_id',
                    field=models.CharField(
                        blank=True,
                        help_text='URLに使われるランダムな共有ID',
                        max_length=8,
                        null=True,
                        verbose_name='共有ID',
                    ),
                ),
            ],
            database_operations=[],
        ),
        # Step 2: 既存レコードにランダムな share_id を設定
        migrations.RunPython(
            populate_share_ids,
            migrations.RunPython.noop,
        ),
        # Step 3: PostgreSQL 限定 - 前回デプロイの残骸インデックスをクリーンアップ
        migrations.RunPython(
            cleanup_pg_indexes,
            migrations.RunPython.noop,
        ),
        # Step 4: null不許容・ユニーク制約ありに変更 (Django が正しくインデックスを作成)
        migrations.AlterField(
            model_name='song',
            name='share_id',
            field=models.CharField(
                default=generate_share_id,
                help_text='URLに使われるランダムな共有ID',
                max_length=8,
                unique=True,
                verbose_name='共有ID',
            ),
        ),
    ]
