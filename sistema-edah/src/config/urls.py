from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "SYS_EDAH"
admin.site.site_title = "SYS_EDAH"
admin.site.index_title = "Administração"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("church.urls")),
    path("api/v1/", include("church.api_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
