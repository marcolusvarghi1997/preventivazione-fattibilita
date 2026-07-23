from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "development-only-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
LAN_SCRIPT_ACTIVE = env_bool("LAN_SCRIPT_ACTIVE", False)
ALLOWED_HOSTS = [v.strip() for v in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if v.strip()]
CSRF_TRUSTED_ORIGINS = [v.strip() for v in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if v.strip()]

INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.catalog",
    "apps.quotes",
    "apps.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.catalog.middleware.LanAccessMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "apps.catalog.context_processors.site_configuration",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

if os.getenv("DB_ENGINE", "sqlite").lower() in {"postgres", "postgresql"}:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "preventivi"),
        "USER": os.getenv("DB_USER", "preventivi"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(os.getenv("SQLITE_DB_PATH", BASE_DIR / "db.sqlite3")),
        "OPTIONS": {"timeout": 20},
    }}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "it-it"
TIME_ZONE = "Europe/Rome"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = Path(os.getenv("STATIC_ROOT", BASE_DIR / "staticfiles"))
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "media"))
STORAGES = {"staticfiles": {"BACKEND": (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
    if DEBUG else "config.storage.JazzminCompatibleManifestStaticFilesStorage"
)}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "quotes:dashboard"
LOGOUT_REDIRECT_URL = "login"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)
CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)

COMPANY = {
    "name": os.getenv("COMPANY_NAME", "Azienda Carpenteria"),
    "address": os.getenv("COMPANY_ADDRESS", ""),
    "vat": os.getenv("COMPANY_VAT", ""),
    "email": os.getenv("COMPANY_EMAIL", ""),
    "phone": os.getenv("COMPANY_PHONE", ""),
    "logo_path": os.getenv("COMPANY_LOGO_PATH", ""),
    "terms": os.getenv("COMPANY_TERMS", "Validita e condizioni da definire."),
}

JAZZMIN_SETTINGS = {
    "site_title": "Amministrazione preventivi",
    "site_header": "Superadmin",
    "site_brand": "Preventivazione",
    "site_logo": "images/officine-pollastri-logo.png",
    "login_logo": "images/officine-pollastri-logo.png",
    "site_icon": "images/favicon.png",
    "welcome_sign": "Gestione azienda, utenti e configurazione",
    "copyright": "Officine Pollastri",
    "search_model": ["quotes.Quote", "catalog.Client", "catalog.Material"],
    "custom_css": "css/admin-overrides.css",
    "custom_links": {
        "catalog": [{
            "name": "Gestione LAN",
            "url": "/admin/rete/",
            "icon": "fas fa-network-wired",
        }],
    },
    "show_ui_builder": False,
    "navigation_expanded": True,
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "catalog.Client": "fas fa-building",
        "catalog.ClientContact": "fas fa-address-card",
        "catalog.Material": "fas fa-layer-group",
        "catalog.ProductionResource": "fas fa-industry",
        "catalog.SiteConfiguration": "fas fa-sliders-h",
        "quotes.Quote": "fas fa-file-invoice-dollar",
    },
}

JAZZMIN_UI_TWEAKS = {
    "theme": "flatly",
    "navbar": "navbar-white navbar-light",
    "sidebar": "sidebar-dark-primary",
    "accent": "accent-info",
    "button_classes": {"primary": "btn-primary", "secondary": "btn-outline-secondary"},
}
