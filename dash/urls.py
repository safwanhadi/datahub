"""
URL configuration for dash project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/internal/v1/', include('api_internal.urls')),
    path('api/external/v1/', include('api_external.urls')),
    path(
        'schema/internal/',
        SpectacularAPIView.as_view(
            urlconf='dash.schema_internal_urls',
            authentication_classes=[SessionAuthentication],
            permission_classes=[IsAuthenticated],
            custom_settings={
                'TITLE': 'SIMRS DataHub Internal API',
                'DESCRIPTION': 'Kontrak API khusus dashboard dan pengguna internal rumah sakit.',
            },
        ),
        name='internal-schema',
    ),
    path(
        'docs/internal/',
        SpectacularSwaggerView.as_view(
            url_name='internal-schema',
            authentication_classes=[SessionAuthentication],
            permission_classes=[IsAuthenticated],
        ),
        name='internal-docs',
    ),
    path(
        'schema/external/',
        SpectacularAPIView.as_view(
            urlconf='dash.schema_external_urls',
            permission_classes=[AllowAny],
            custom_settings={
                'TITLE': 'SIMRS DataHub External API',
                'DESCRIPTION': 'Kontrak API terverifikasi untuk aplikasi mitra yang diizinkan.',
            },
        ),
        name='external-schema',
    ),
    path(
        'docs/external/',
        SpectacularSwaggerView.as_view(
            url_name='external-schema',
            permission_classes=[AllowAny],
        ),
        name='external-docs',
    ),
    path('accounts/', include('myaccount.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('verification.urls')),
]

if settings.DEBUG:
    urlpatterns += [
        path('mock/simrs/v1/', include('simrs_mock.urls')),
        path(
            'schema/mock-simrs/',
            SpectacularAPIView.as_view(
                urlconf='dash.schema_mock_simrs_urls',
                permission_classes=[AllowAny],
                custom_settings={
                    'TITLE': 'Mock SIMRS Source API',
                    'DESCRIPTION': 'Kontrak kelompok data yang harus disediakan tim SIMRS.',
                },
            ),
            name='mock-simrs-schema',
        ),
        path(
            'docs/mock-simrs/',
            SpectacularSwaggerView.as_view(url_name='mock-simrs-schema', permission_classes=[AllowAny]),
            name='mock-simrs-docs',
        ),
    ]
