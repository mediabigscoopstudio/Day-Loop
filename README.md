# Day Loop

Multi-vendor supplement marketplace. One Django project serves three
surfaces by subdomain, plus an API stub.

| Host | Surface | URLconf |
|---|---|---|
| `www.<parent>` (default) | Customer storefront, all purchases | `dayloop/urls_www.py` |
| `seller.<parent>` | Seller portal | `dayloop/urls_seller.py` |
| `dash.<parent>` | Internal admin panel; Django admin at `/admin/` | `dayloop/urls_dash.py` |
| `api.<parent>` | API and webhooks (stub: `/health/`) | `dayloop/urls_api.py` |

Routing is done by [django-hosts](https://django-hosts.readthedocs.io/). Host
patterns are in `dayloop/hosts.py`. Unknown subdomains fall back to `www`.

## Run locally

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py createsuperuser   # for dash.localhost:8000/admin/
./.venv/bin/python manage.py runserver
```

Then open:

- http://www.localhost:8000/
- http://seller.localhost:8000/
- http://dash.localhost:8000/
- http://dash.localhost:8000/admin/
- http://api.localhost:8000/health/

`localhost:8000` (bare) redirects to `www.localhost:8000`. The `*.localhost`
names resolve to 127.0.0.1 in modern browsers and on macOS.

## Admin dashboard (dash host)

`dash.localhost:8000` is the internal admin panel: Overview, Orders, Sellers, Products
(with a Categories tab), Customers and Analytics, plus global search and a notification bell.

- **Access:** active superusers only. Enforced three ways: `dash.middleware.DashAccessMiddleware`
  (host-scoped), `SuperuserRequiredMixin` on every view (HTMX and JSON requests get 403), and the
  login view itself. Failed logins are throttled (5 per 15 minutes per IP + username).
  Django's own admin is at `/admin/` under the same rule.
- **Popups:** add/edit/confirm flows are `<dialog>` modals loaded with HTMX into `#modal-root`.
  Reusable pieces live in the `ui` app (`ui/templates/ui/`, `ui/static/ui/`) so the seller portal can reuse them.
  HTMX and Chart.js are vendored in `ui/static/ui/vendor/` (no CDN at runtime).
- **Environment:** the database password is read from `DJANGO_DB_PASSWORD`.
- **Demo data (optional):** `python manage.py seed_dash_demo` seeds categories, and sellers/products/orders
  attached to *existing* non-superuser accounts. It never creates users and is never run automatically.
- **Tests:** `python manage.py test dash`

## Seller portal (seller host)

`seller.localhost:8000` is where sellers register, onboard and run their business.

- **Who can log in:** an active account with a `SellerProfile` that is not staff or a superuser. Customers and staff
  get the same generic error as a wrong password. Sellers register themselves at `/register/`; no accounts are created for them.
- **Approval gate:** until an admin approves the application a seller sees only Status, Account and onboarding.
- **Onboarding:** a 4-step popup wizard (business, compliance, bank & operations, review). Each step saves a draft.
- **Products:** one long page with collapsible cards (basics, variants, images and highlights, SEO, A+ content).
  A product needs at least one complete variant (price, stock, expiry and full package dimensions) before it can be
  submitted. An admin approves it in the dash (Products -> review), which makes it Live.
- **Orders:** one checkout becomes one `Order` plus one `SellerOrder` per seller. Each seller only sees their own.
  Pipeline: New -> Accepted -> Packed -> Shipped -> Delivered, plus Cancelled and Returned.
- **Money:** margin 5% of purchase value, GST 18% on the margin only, payout = purchase value - margin - GST on margin
  (10,000 -> 500 -> 90 -> 9,410). Rates are stored on each SellerOrder. See `orders/services/money.py`.
- **Payouts:** credited on delivery, debited on return. Admins settle them in the dash (Payouts).
- **Uploads** (logo, documents, product images) are written to `MEDIA_ROOT`. Tests use a temporary folder.
- **Tests:** `python manage.py test seller orders catalog`

## Sessions and CSRF

- Each surface has its own session cookie: `dl_www_sid`, `dl_seller_sid`,
  `dl_dash_sid`. Cookies are host-only (no `SESSION_COOKIE_DOMAIN`), so a login
  on one host never reaches another.
- CSRF uses `CSRF_USE_SESSIONS = True`, so the CSRF secret lives in the same
  per-host session. There is no separate `csrftoken` cookie.

## Production

Set these environment variables:

| Variable | Example | Purpose |
|---|---|---|
| `DJANGO_PARENT_HOST` | `dayloop.example.com` | Base domain. Hosts become `www.`, `seller.`, `dash.`, `api.` |
| `DJANGO_SCHEME` | `https` | Scheme for CSRF origins and cross-host links |
| `DJANGO_SECRET_KEY` | (secret) | Required |
| `DJANGO_DEBUG` | `0` | Turn debug off |
| `DJANGO_EXTRA_ALLOWED_HOSTS` | `extra.example.com` | Optional, comma-separated |

**Apex redirect.** The bare domain redirects to `www` in two places:
`dayloop/middleware.py:ApexRedirectMiddleware` (app fallback) and, preferably,
at the proxy or load balancer (for example `example.com` → `https://www.example.com`).

**Cross-host links.** Use `reverse('seller-home', host='seller')` in Python, or
`{% host_url 'seller-home' host 'seller' %}` in templates (`{% load hosts %}`).
