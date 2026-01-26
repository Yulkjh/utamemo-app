# ドメイン設定とDNSレコードの確認

## 概要

このドキュメントでは、UTAMEMOアプリケーションのカスタムドメイン設定とDNSレコードの構成方法について説明します。

## 現在の設定

### 設定済みドメイン

アプリケーションは以下のドメインをサポートするように設定されています：

- `utamemo.com`
- `www.utamemo.com`

これらのドメインは `myproject/myproject/settings.py` の `ALLOWED_HOSTS` に追加されています。

## Renderでのカスタムドメイン設定

### 1. Renderダッシュボードでのドメイン追加

1. [Render Dashboard](https://dashboard.render.com/) にログイン
2. UTAMEMOアプリケーションのサービスを選択
3. 「Settings」タブに移動
4. 「Custom Domains」セクションを見つける
5. 「Add Custom Domain」ボタンをクリック
6. ドメイン名を入力（例：`utamemo.com` または `www.utamemo.com`）
7. 「Save」をクリック

### 2. DNSレコードの設定

Renderがドメインを検証するために、以下のDNSレコードを設定する必要があります。

#### Aレコード（ルートドメイン用）

ルートドメイン `utamemo.com` の場合：

| タイプ | ホスト名 | 値 | TTL |
|--------|----------|-----|-----|
| A | @ | [RenderのIPアドレス] | 3600 |

**注意**: RenderのIPアドレスは、Renderダッシュボードの「Custom Domains」セクションに表示されます。

#### CNAMEレコード（wwwサブドメイン用）

`www.utamemo.com` の場合：

| タイプ | ホスト名 | 値 | TTL |
|--------|----------|-----|-----|
| CNAME | www | [Renderが提供するURL] | 3600 |

**例**: `your-app-name.onrender.com`

#### 代替設定：CNAMEフラットニング対応の場合

一部のDNSプロバイダーは、ルートドメインでCNAMEレコードをサポートしています（CNAMEフラットニング、ANAME、ALIASなど）：

| タイプ | ホスト名 | 値 | TTL |
|--------|----------|-----|-----|
| CNAME/ALIAS | @ | [Renderが提供するURL] | 3600 |
| CNAME | www | [Renderが提供するURL] | 3600 |

### 3. SSL/TLS証明書の設定

Renderは自動的にLet's Encryptを使用してSSL/TLS証明書を発行します：

1. DNSレコードが正しく設定されていることを確認
2. DNS変更が反映されるまで待機（最大48時間、通常は数分〜数時間）
3. Renderが自動的にSSL証明書を発行
4. 証明書のステータスは「Custom Domains」セクションで確認可能

## DNSプロバイダー別の設定例

### Cloudflare

1. Cloudflareダッシュボードにログイン
2. 対象のドメインを選択
3. 「DNS」タブに移動
4. 「Add record」をクリック
5. 上記のAレコードまたはCNAMEレコードを追加
6. 「Save」をクリック
7. プロキシステータスは「DNS only」（グレーの雲）に設定することを推奨

### Google Domains / Google Cloud DNS

1. Google DomainsまたはGoogle Cloud Consoleにログイン
2. 対象のドメインを選択
3. 「DNS」設定に移動
4. 「カスタムレコードを管理」を選択
5. 上記のAレコードまたはCNAMEレコードを追加
6. 変更を保存

### お名前.com

1. お名前.comにログイン
2. 「ドメイン設定」→「DNS設定」を選択
3. 対象のドメインを選択
4. 「DNSレコード設定を利用する」を選択
5. 上記のAレコードまたはCNAMEレコードを追加
6. 「確認画面へ進む」→「設定する」をクリック

### ムームードメイン

1. ムームードメインにログイン
2. 「コントロールパネル」→「ドメイン操作」→「ムームーDNS」
3. 対象のドメインの「変更」をクリック
4. 「カスタム設定」を選択
5. 上記のAレコードまたはCNAMEレコードを追加
6. 「セットアップ情報変更」をクリック

## 確認手順

### 1. DNS設定の確認

以下のコマンドを使用してDNS設定を確認できます：

```bash
# Aレコードの確認
dig utamemo.com A

# CNAMEレコードの確認
dig www.utamemo.com CNAME

# すべてのDNSレコードの確認
dig utamemo.com ANY
```

Windowsの場合：

```cmd
# Aレコードの確認
nslookup utamemo.com

# CNAMEレコードの確認
nslookup www.utamemo.com
```

### 2. SSL証明書の確認

ブラウザで以下を確認：

1. `https://utamemo.com` にアクセス
2. アドレスバーの鍵アイコンをクリック
3. 証明書情報を確認
4. 発行者が「Let's Encrypt」であることを確認

オンラインツールでの確認：
- [SSL Labs Server Test](https://www.ssllabs.com/ssltest/)
- [WhyNoPadlock](https://www.whynopadlock.com/)

### 3. リダイレクトの確認

以下のリダイレクトが正しく機能することを確認：

- `http://utamemo.com` → `https://utamemo.com`
- `http://www.utamemo.com` → `https://www.utamemo.com`
- `https://www.utamemo.com` → `https://utamemo.com`（wwwなし優先の場合）

## トラブルシューティング

### DNS変更が反映されない

**原因**:
- DNS変更は最大48時間かかる場合がある（通常は数分〜数時間）
- DNSキャッシュの問題

**解決策**:
```bash
# DNSキャッシュをクリア（Mac）
sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder

# DNSキャッシュをクリア（Windows）
ipconfig /flushdns

# DNSキャッシュをクリア（Linux）
sudo systemd-resolve --flush-caches
```

### SSL証明書が発行されない

**原因**:
- DNS設定が正しくない
- DNS変更がまだ反映されていない
- CAA（Certification Authority Authorization）レコードがLet's Encryptをブロックしている

**解決策**:
1. DNS設定を再確認
2. 24時間待ってから再試行
3. CAAレコードを確認（設定している場合）：
   ```
   utamemo.com. CAA 0 issue "letsencrypt.org"
   ```

### 「この接続ではプライバシーが保護されません」エラー

**原因**:
- SSL証明書がまだ発行されていない
- 証明書が期限切れ
- DNS設定の問題

**解決策**:
1. Renderダッシュボードで証明書のステータスを確認
2. DNS設定を確認
3. 必要に応じてRenderサポートに問い合わせ

### 「Not Found」または404エラー

**原因**:
- `ALLOWED_HOSTS` にドメインが追加されていない
- Renderでドメインが正しく設定されていない

**解決策**:
1. `settings.py` の `ALLOWED_HOSTS` を確認：
   ```python
   ALLOWED_HOSTS.extend(['utamemo.com', 'www.utamemo.com'])
   ```
2. Renderダッシュボードでドメイン設定を確認
3. アプリケーションを再デプロイ

### wwwありとwwwなしのリダイレクト

**優先ドメインをwwwなしに設定する場合**:

Renderでは、プライマリドメインを設定できます：

1. Renderダッシュボードの「Custom Domains」セクション
2. `utamemo.com` を「Primary」として設定
3. これにより、`www.utamemo.com` は自動的に `utamemo.com` にリダイレクトされます

## 設定チェックリスト

- [ ] Renderダッシュボードでカスタムドメインを追加
- [ ] DNSプロバイダーでAレコード（またはCNAME/ALIAS）を設定
- [ ] DNSプロバイダーでCNAMEレコード（www用）を設定
- [ ] DNS変更の反映を確認（`dig`または`nslookup`コマンド）
- [ ] RenderでSSL証明書が自動発行されたことを確認
- [ ] HTTPSでサイトにアクセスできることを確認
- [ ] HTTPからHTTPSへのリダイレクトを確認
- [ ] ブラウザで証明書情報を確認
- [ ] `settings.py`の`ALLOWED_HOSTS`にドメインが含まれていることを確認

## 参考リンク

- [Render - Custom Domains](https://render.com/docs/custom-domains)
- [Render - SSL/TLS Certificates](https://render.com/docs/tls)
- [Django - ALLOWED_HOSTS](https://docs.djangoproject.com/en/5.2/ref/settings/#allowed-hosts)
- [Let's Encrypt](https://letsencrypt.org/)

## サポート

問題が解決しない場合は、以下のサポートチャンネルをご利用ください：

- Render Support: https://render.com/support
- Django Documentation: https://docs.djangoproject.com/
- UTAMEMOリポジトリのIssues: https://github.com/Yulkjh/utamemo-app/issues

---

**最終更新**: 2026年1月27日  
**バージョン**: 1.0
