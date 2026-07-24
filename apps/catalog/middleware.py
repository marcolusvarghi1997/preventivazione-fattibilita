from datetime import timedelta
import hmac
from ipaddress import ip_address

from django.conf import settings
from django.db import OperationalError, ProgrammingError
from django.db.models import F
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from .models import LanDeviceAccess
from .network import get_remote_mac


class LanAccessMiddleware:
    """Registra i PC remoti e lascia entrare solo quelli approvati dal superadmin."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        remote = request.META.get("REMOTE_ADDR", "127.0.0.1").split("%", 1)[0]
        try:
            parsed_ip = ip_address(remote)
        except ValueError:
            return HttpResponseForbidden("Indirizzo di rete non valido.")

        if parsed_ip.is_loopback:
            return self.get_response(request)

        static_prefix = f"/{settings.STATIC_URL.lstrip('/')}"
        media_prefix = f"/{settings.MEDIA_URL.lstrip('/')}"
        if request.path.startswith((static_prefix, media_prefix)):
            return self.get_response(request)

        logout_paths = {reverse("logout"), reverse("admin:logout")}
        logout_path = request.path in logout_paths
        lan_management_path = request.path.startswith(reverse("catalog:lan_settings"))
        user = getattr(request, "user", None)
        is_superuser = bool(
            user is not None and user.is_authenticated and user.is_active and user.is_superuser
        )
        remote_ip = str(parsed_ip)
        remote_mac = get_remote_mac(remote_ip)
        request.lan_remote_ip = remote_ip
        request.lan_remote_mac = remote_mac
        identity_key = f"{remote_ip}|{remote_mac or ''}"
        suppressed_identity = (
            request.session.get("lan_suppress_detection_identity") if is_superuser else None
        )
        if is_superuser and lan_management_path and suppressed_identity == identity_key:
            return self.get_response(request)
        if suppressed_identity:
            request.session.pop("lan_suppress_detection_identity", None)
        request.session.pop("lan_suppress_detection_ip", None)

        device = None
        now = timezone.now()
        try:
            device, created = LanDeviceAccess.objects.get_or_create(
                ip_address=remote_ip,
                defaults={"mac_address": remote_mac or "", "last_seen_at": now},
            )
            identity_changed = bool(
                not created
                and remote_mac
                and not hmac.compare_digest(device.mac_address, remote_mac)
            )
            if identity_changed:
                LanDeviceAccess.objects.filter(pk=device.pk).update(
                    mac_address=remote_mac,
                    status=LanDeviceAccess.Status.PENDING,
                    first_seen_at=now,
                    last_seen_at=now,
                    request_count=1,
                    decided_at=None,
                    decided_by=None,
                )
                device.mac_address = remote_mac
                device.status = LanDeviceAccess.Status.PENDING
                device.first_seen_at = now
                device.last_seen_at = now
                device.request_count = 1
                device.decided_at = None
                device.decided_by = None
            elif not created:
                if is_superuser or device.status == LanDeviceAccess.Status.ALLOWED:
                    if device.last_seen_at < now - timedelta(minutes=1):
                        LanDeviceAccess.objects.filter(pk=device.pk).update(last_seen_at=now)
                else:
                    LanDeviceAccess.objects.filter(pk=device.pk).update(
                        last_seen_at=now,
                        request_count=F("request_count") + 1,
                    )
        except (OperationalError, ProgrammingError):
            return HttpResponseForbidden("Gestione degli accessi LAN non ancora disponibile.")

        identity_verified = bool(
            remote_mac
            and device.mac_address
            and hmac.compare_digest(device.mac_address, remote_mac)
        )
        if (
            (is_superuser and lan_management_path)
            or logout_path
            or (
                device.status == LanDeviceAccess.Status.ALLOWED
                and identity_verified
            )
        ):
            return self.get_response(request)

        return render(
            request,
            "catalog/lan_access_blocked.html",
            {
                "device": device,
                "remote_ip": remote_ip,
                "remote_mac": remote_mac,
                "mac_unavailable": remote_mac is None,
                "access_denied": device.status == LanDeviceAccess.Status.DENIED,
            },
            status=403,
        )
