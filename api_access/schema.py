from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SimaduOpaqueTokenScheme(OpenApiAuthenticationExtension):
    target_class = "api_access.authentication.SimaduOpaqueTokenAuthentication"
    name = "SimaduBearerAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "oauth2",
            "description": "Opaque access token yang diterbitkan SIMADU.",
            "flows": {
                "clientCredentials": {
                    "tokenUrl": settings.SIMADU_TOKEN_URL,
                    "scopes": {
                        "read:dash": "Membaca API terverifikasi DataHub",
                    },
                }
            },
        }
