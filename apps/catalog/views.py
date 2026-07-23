from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache

from .forms import LanSettingsForm
from .models import SiteConfiguration
from .network import get_lan_ipv4_addresses


@never_cache
@login_required
def lan_settings(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    configuration = SiteConfiguration.load()
    form = LanSettingsForm(request.POST if request.method == "POST" else None, instance=configuration)
    if request.method == "POST" and form.is_valid():
        form.save()
        state = "abilitato" if configuration.lan_enabled else "disabilitato"
        messages.success(request, f"Accesso dalla rete locale {state}.")
        return redirect("catalog:lan_settings")

    port = request.get_port()
    lan_urls = [f"http://{address}:{port}" for address in get_lan_ipv4_addresses()]
    return render(request, "catalog/lan_settings.html", {
        "configuration": configuration,
        "form": form,
        "lan_urls": lan_urls,
        "lan_script_active": settings.LAN_SCRIPT_ACTIVE,
        "server_port": port,
    })
