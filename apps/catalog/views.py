from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Case, IntegerField, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import LanDeviceAccess
from .network import get_remote_ip, get_server_connection_info


@never_cache
@login_required
def lan_settings(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    connection_info = get_server_connection_info(request)
    status_order = Case(
        When(status=LanDeviceAccess.Status.PENDING, then=Value(0)),
        When(status=LanDeviceAccess.Status.ALLOWED, then=Value(1)),
        default=Value(2),
        output_field=IntegerField(),
    )
    return render(request, "catalog/lan_settings.html", {
        "lan_devices": LanDeviceAccess.objects.annotate(status_order=status_order).order_by(
            "status_order", "-last_seen_at", "ip_address"
        ),
        "pending_count": LanDeviceAccess.objects.filter(status=LanDeviceAccess.Status.PENDING).count(),
        "current_ip": get_remote_ip(request),
        **connection_info,
    })


@never_cache
@require_POST
@login_required
def decide_lan_access(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied

    decisions = {
        "allow": LanDeviceAccess.Status.ALLOWED,
        "deny": LanDeviceAccess.Status.DENIED,
    }
    status = decisions.get(request.POST.get("decision"))
    if status is None:
        raise Http404

    device = get_object_or_404(LanDeviceAccess, pk=pk)
    device.status = status
    device.decided_at = timezone.now()
    device.decided_by = request.user
    device.save(update_fields=("status", "decided_at", "decided_by"))
    state = "autorizzato" if status == LanDeviceAccess.Status.ALLOWED else "bloccato"
    messages.success(request, f"Il dispositivo {device.ip_address} è stato {state}.")
    return redirect("catalog:lan_settings")


@never_cache
@require_POST
@login_required
def delete_lan_access(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied

    device = get_object_or_404(LanDeviceAccess, pk=pk)
    ip_address = str(device.ip_address)
    if ip_address == get_remote_ip(request):
        request.session["lan_suppress_detection_ip"] = ip_address
    device.delete()
    messages.success(request, f"La richiesta del dispositivo {ip_address} è stata rimossa.")
    return redirect("catalog:lan_settings")
