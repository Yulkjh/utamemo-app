# Domain Setup and DNS Record Verification

## Overview

This document explains how to configure custom domains and DNS records for the UTAMEMO application.

## Current Configuration

### Configured Domains

The application is configured to support the following domains:

- `utamemo.com`
- `www.utamemo.com`

These domains are added to `ALLOWED_HOSTS` in `myproject/myproject/settings.py`.

## Custom Domain Setup on Render

### 1. Add Domain in Render Dashboard

1. Log in to [Render Dashboard](https://dashboard.render.com/)
2. Select your UTAMEMO application service
3. Go to the "Settings" tab
4. Find the "Custom Domains" section
5. Click "Add Custom Domain" button
6. Enter your domain name (e.g., `utamemo.com` or `www.utamemo.com`)
7. Click "Save"

### 2. Configure DNS Records

You need to configure the following DNS records for Render to verify your domain.

#### A Record (for root domain)

For root domain `utamemo.com`:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | @ | [Render's IP Address] | 3600 |

**Note**: Render's IP address will be displayed in the "Custom Domains" section of the Render dashboard.

#### CNAME Record (for www subdomain)

For `www.utamemo.com`:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| CNAME | www | [URL provided by Render] | 3600 |

**Example**: `your-app-name.onrender.com`

#### Alternative: CNAME Flattening Support

Some DNS providers support CNAME records at the root level (CNAME flattening, ANAME, ALIAS, etc.):

| Type | Name | Value | TTL |
|------|------|-------|-----|
| CNAME/ALIAS | @ | [URL provided by Render] | 3600 |
| CNAME | www | [URL provided by Render] | 3600 |

### 3. SSL/TLS Certificate Setup

Render automatically issues SSL/TLS certificates using Let's Encrypt:

1. Ensure DNS records are configured correctly
2. Wait for DNS changes to propagate (up to 48 hours, usually minutes to hours)
3. Render will automatically issue an SSL certificate
4. Certificate status can be checked in the "Custom Domains" section

## DNS Provider-Specific Examples

### Cloudflare

1. Log in to Cloudflare dashboard
2. Select your domain
3. Go to the "DNS" tab
4. Click "Add record"
5. Add the A or CNAME records mentioned above
6. Click "Save"
7. Set proxy status to "DNS only" (gray cloud) recommended

### Google Domains / Google Cloud DNS

1. Log in to Google Domains or Google Cloud Console
2. Select your domain
3. Go to "DNS" settings
4. Select "Manage custom records"
5. Add the A or CNAME records mentioned above
6. Save changes

### Other Providers

Similar steps apply to other DNS providers. Consult your provider's documentation for specific instructions.

## Verification Steps

### 1. Verify DNS Configuration

Use the following commands to verify DNS settings:

```bash
# Check A record
dig utamemo.com A

# Check CNAME record
dig www.utamemo.com CNAME

# Check all DNS records
dig utamemo.com ANY
```

On Windows:

```cmd
# Check A record
nslookup utamemo.com

# Check CNAME record
nslookup www.utamemo.com
```

### 2. Verify SSL Certificate

In your browser:

1. Visit `https://utamemo.com`
2. Click the lock icon in the address bar
3. View certificate information
4. Verify issuer is "Let's Encrypt"

Online tools:
- [SSL Labs Server Test](https://www.ssllabs.com/ssltest/)
- [WhyNoPadlock](https://www.whynopadlock.com/)

### 3. Verify Redirects

Confirm the following redirects work correctly:

- `http://utamemo.com` → `https://utamemo.com`
- `http://www.utamemo.com` → `https://www.utamemo.com`
- `https://www.utamemo.com` → `https://utamemo.com` (if preferring non-www)

## Troubleshooting

### DNS Changes Not Reflecting

**Cause**:
- DNS changes can take up to 48 hours (usually minutes to hours)
- DNS cache issues

**Solution**:
```bash
# Flush DNS cache (Mac)
sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder

# Flush DNS cache (Windows)
ipconfig /flushdns

# Flush DNS cache (Linux)
sudo systemd-resolve --flush-caches
```

### SSL Certificate Not Issued

**Cause**:
- Incorrect DNS configuration
- DNS changes haven't propagated yet
- CAA (Certification Authority Authorization) records blocking Let's Encrypt

**Solution**:
1. Re-check DNS configuration
2. Wait 24 hours and retry
3. Check CAA records (if configured):
   ```
   utamemo.com. CAA 0 issue "letsencrypt.org"
   ```

### "Your connection is not private" Error

**Cause**:
- SSL certificate hasn't been issued yet
- Certificate expired
- DNS configuration issue

**Solution**:
1. Check certificate status in Render dashboard
2. Verify DNS configuration
3. Contact Render support if needed

### "Not Found" or 404 Error

**Cause**:
- Domain not added to `ALLOWED_HOSTS`
- Domain not configured correctly in Render

**Solution**:
1. Check `ALLOWED_HOSTS` in `settings.py`:
   ```python
   ALLOWED_HOSTS.extend(['utamemo.com', 'www.utamemo.com'])
   ```
2. Verify domain settings in Render dashboard
3. Redeploy the application

### www vs non-www Redirect

**To set non-www as primary domain**:

In Render, you can set a primary domain:

1. Go to "Custom Domains" section in Render dashboard
2. Set `utamemo.com` as "Primary"
3. This will automatically redirect `www.utamemo.com` to `utamemo.com`

## Configuration Checklist

- [ ] Add custom domain in Render dashboard
- [ ] Configure A record (or CNAME/ALIAS) in DNS provider
- [ ] Configure CNAME record (for www) in DNS provider
- [ ] Verify DNS propagation (`dig` or `nslookup` command)
- [ ] Confirm SSL certificate auto-issued in Render
- [ ] Access site via HTTPS
- [ ] Verify HTTP to HTTPS redirect
- [ ] Check certificate information in browser
- [ ] Confirm domain is in `ALLOWED_HOSTS` in `settings.py`

## References

- [Render - Custom Domains](https://render.com/docs/custom-domains)
- [Render - SSL/TLS Certificates](https://render.com/docs/tls)
- [Django - ALLOWED_HOSTS](https://docs.djangoproject.com/en/5.2/ref/settings/#allowed-hosts)
- [Let's Encrypt](https://letsencrypt.org/)

## Support

If you continue to experience issues, please use the following support channels:

- Render Support: https://render.com/support
- Django Documentation: https://docs.djangoproject.com/
- UTAMEMO Repository Issues: https://github.com/Yulkjh/utamemo-app/issues

---

**Last Updated**: January 27, 2026  
**Version**: 1.0
