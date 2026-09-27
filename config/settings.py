"""
Django settings for MAHAY project.
All secrets and environment-specific values come from .env (python-decouple).
"""

from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent


# --- Security -------------------------------------------------------------

SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="", cast=Csv())

# Addresses of our own reverse proxies (nginx). A visitor can put anything in
# X-Forwarded-For, so that header is believed only when the request truly arrived
# through one of these. Empty (development): the header is ignored entirely.
TRUSTED_PROXIES = config("TRUSTED_PROXIES", default="", cast=Csv())


# --- Applications ---------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
   
]

THIRD_PARTY_APPS = []

LOCAL_APPS = [
    "accounts",
    "domains",
    "products",
    "content",
    "approvals",
    "commerce",
    "services",
    "pages",
    "inbox",
    "collaboration",
    "finance",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "products.context_processors.store_nav",
                "commerce.context_processors.cart",
                "pages.context_processors.footer_pages",
                "services.context_processors.contact_channels",
                "inbox.context_processors.unread",
                "accounts.context_processors.pending_work",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Database -------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default=5432, cast=int),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Authentication -------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        # Password must not resemble the mobile number, name or email
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("mobile_number", "first_name", "last_name", "email")},
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- Internationalization -------------------------------------------------

LANGUAGE_CODE = "fa"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True


# --- Static files ---------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]


# Public uploaded files (covers, ...): anyone with the link can open them
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Paid content (lesson videos, attachments): NOT reachable by URL; served only through a view that checks access.
# Later this can be moved to a cloud video/object storage by changing the storage, not the models.
PROTECTED_MEDIA_ROOT = BASE_DIR / "protected_media"

# --- SMS -------------------------------------------------------------------
# console: printed in the terminal (development) | disabled: sign-up verification is skipped
# A real provider (e.g. kavenegar) is switched on here once credit is bought — no code changes.

SMS_BACKEND = config("SMS_BACKEND", default="console")
SMS_API_KEY = config("SMS_API_KEY", default="")
SMS_SENDER = config("SMS_SENDER", default="")

# --- Payment (ZarinPal) ----------------------------------------------------
# sandbox: no real money moves. live: needs a real merchant id from ZarinPal.

# How much of a project is asked for before the work starts; a consultation is always paid in
# full. A single request can be given its own percentage in the admin.
SERVICE_PREPAY_PERCENT = config("SERVICE_PREPAY_PERCENT", default=50, cast=int)

# Consulting is sold by the quarter of an hour. A domain may set its own rate; this is the
# fallback. Zero means no price can be worked out, and the customer is quoted by hand instead.
CONSULTING_RATE_PER_QUARTER = config("CONSULTING_RATE_PER_QUARTER", default=0, cast=int)

ZARINPAL_MODE = config("ZARINPAL_MODE", default="sandbox")
ZARINPAL_MERCHANT_ID = config("ZARINPAL_MERCHANT_ID", default="00000000-0000-0000-0000-000000000000")

# --- Email ----------------------------------------------------------------
# Development: emails are printed in the terminal instead of being sent.

EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="MAHAY <noreply@mahay.local>")


LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

PASSWORD_RESET_TIMEOUT = 60 * 60 * 2  # reset links expire after 2 hours


# --- HTTPS and cookies ----------------------------------------------------
# Everything here stays off while DEBUG is on, so development over plain http keeps working.

SESSION_COOKIE_SECURE = not DEBUG  # the session cookie never travels over plain http
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True

# Behind nginx the connection reaches Django as http, so without this the redirect above
# would loop forever. Read only from our own proxy: otherwise a visitor could claim their
# plain request was already secure and skip the redirect.
if TRUSTED_PROXIES:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Browsers refuse plain http for this domain for a year. They remember it for the whole
# period and it cannot be taken back quickly, so set SECURE_HSTS_SECONDS=0 in .env for the
# first deploys and raise it once HTTPS is known to work.
SECURE_HSTS_SECONDS = 0 if DEBUG else config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = bool(SECURE_HSTS_SECONDS)
SECURE_HSTS_PRELOAD = bool(SECURE_HSTS_SECONDS)

# The https addresses the site is served from, e.g. https://mahay.ir — needed for CSRF.
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())