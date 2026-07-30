# データ提供元コンプライアンス（Data Partner Compliance）

Clearnote社との覚書のような、外部企業・団体からノートデータ等の提供を受ける契約（覚書・MOU）を
締結した場合に、その義務を技術的にどう満たすかをまとめる。Clearnote固有の実装ではなく、
今後どの提供元とも同じ仕組みで対応できるよう汎用化してある。

## 背景

2026年時点で、Clearnote社とのデータ提供は「協業を提案する打診段階」であり、実際のデータは
まだシステムに存在しない（`docs/meeting_pitch_clearnote.md` 参照）。一方、コクヨ社からは
既にノートデータ（CamiApp等）の提供を受けており、`training/export_training_data.py` の
コメントにその旨の記載がある。この2社は「学習データを外部から提供してもらい、AI学習にのみ
使う」という構造上まったく同じ契約であり、この仕組みはどちらにも同じように適用される。

## 覚書の主な義務と、対応する仕組み

| 条項 | 義務の要旨 | 対応する仕組み |
|------|-----------|---------------|
| 第2条 | 提供データの範囲を明確にする | `DataPartner.permitted_scope` に許諾範囲を記録 |
| 第3条 | 目的外利用・第三者開示の禁止、限定されたメンバーのみ取扱可 | `DataPartner.authorized_users`（`DataPartnerAuthorization` 経由）+ `TrainingData.objects.visible_to(user)` によるアクセス制御。superuser以外は許可されたメンバーしか該当データを閲覧・編集・ダウンロードできない |
| 第4条 | 安全管理、漏洩/紛失/改ざん防止、削除依頼時の復元不可能な削除 | `TrainingData.data_partner` (on_delete=PROTECT) でどのデータがどの提供元由来か追跡。`purge_partner_data` コマンドでDB（`TrainingData`+`TrainingDataReview`）とJSONファイル（`training/data/*.json`、スナップショット含む）の両方から完全削除。`.gitignore` で該当JSONファイルを追跡対象から除外 |
| 第5条 | 活用状況の報告 | `partner_data_report` コマンドで件数・期間・アクセス履歴（`PartnerDataAccessLog`）をレポート出力 |
| 第6条 | クレジット表記 | コード上の強制はできない（対外発表そのものの内容の問題）。下記チェックリストで運用上リマインドする |
| 第7条 | 秘密保持 | 既存のセキュリティ運用（`.env`管理、admin 2FA等）の範囲。追加のコード変更なし |

## 新しいパートナーを迎える手順

1. Django admin で `DataPartner` を作成（`slug`, `name`, `contract_reference`, `permitted_scope` を記入）。
2. 同じく admin（`DataPartnerAuthorization`）で、覚書上「事前に通知済み」のスタッフだけを
   `authorized_users` として登録する。ここに入っていないスタッフは、そのパートナーのデータを
   一覧にも詳細にもダウンロードにも表示できない（superuserを除く）。
3. 提供元から受け取ったデータを、既存の instruction/input/output 形式のJSONにまとめた上で、

   ```
   python manage.py import_training_data --path <受領したファイル> --partner <slug>
   ```

   でインポートする。既存の無タグレコードと同じ内容がある場合は自動的にタグ付けし警告を出す。
   別パートナーのデータと衝突する場合は誤帰属を避けるためスキップする。
4. 開発完了時、または提供元から削除依頼を受けた場合:

   ```
   python manage.py purge_partner_data <slug>            # まずプレビュー（何も削除しない）
   python manage.py purge_partner_data <slug> --yes --reason "削除依頼受領のため"
   ```

5. 進捗・完了の報告が必要なタイミングで:

   ```
   python manage.py partner_data_report <slug>
   ```

   の出力をそのまま、または要約して提供元に共有する。
6. メディア取材・コンペ・学会発表・プレスリリース等の対外発表を行う際は、
   `DataPartner.contract_reference` を確認し、クレジット表記が必要な提供元かどうか確認する
   （第6条：これはコードでは強制できない、必ず人間が確認すること）。

## 既知の限界（正直に書いておく）

- **過去データは遡ってタグ付けできない。** この仕組みが導入される前に取り込まれた
  `TrainingData`（約1044件、2026年時点）や、既にコクヨ由来のデータが混ざっている可能性のある
  `Lyrics.original_text` は、どのレコードがどの提供元由来かを機械的に判別する手段がない
  （`export_training_data.py` の `classify_source_type()` は文章の見た目に基づく分類であり、
  提供元の記録ではない）。もし今後コクヨ社から削除依頼が来た場合、対象を正確に特定するのは
  技術的に困難であり、これはエンジニアリングでは解決できない過去の運用上のリスクとして
  認識しておく必要がある。
- **`git rm --cached` は今後の追跡を止めるだけで、過去のコミット履歴は消えない。** もし
  過去に提供元データがコミットされていた場合、真に「復元不可能な削除」を満たすには
  git履歴の書き換え（BFG/git-filter-repoでの履歴からの完全除去＋force push）が別途必要になる。
  これは共有履歴を書き換える破壊的な操作のため、実施する場合は必ず事前にチームの合意を取ること。
- 第6条（クレジット表記）と第7条（秘密保持）は、対外コミュニケーションや日常のセキュリティ運用
  そのものの話であり、コードで強制できるポイントが存在しない。上記チェックリストで
  リマインドする以上のことはできない。
