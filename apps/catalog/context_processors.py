from django.conf import settings
from django.db import OperationalError, ProgrammingError

from .models import SiteConfiguration


def site_configuration(request):
    try:
        config = SiteConfiguration.load()
    except (OperationalError, ProgrammingError):
        config = None
    return {"site_config": config, "company_defaults": settings.COMPANY}
