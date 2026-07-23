from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path


admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser

urlpatterns = [
    path("admin/", include("apps.catalog.urls")),
    path("admin/", admin.site.urls),
    path("accesso/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("esci/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.quotes.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
