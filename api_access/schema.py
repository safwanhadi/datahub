from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SimaduOpaqueTokenScheme(OpenApiAuthenticationExtension):
    target_class = "api_access.authentication.SimaduOpaqueTokenAuthentication"
    name = "SimaduBearerAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "Opaque token SIMADU",
            "description": (
                "Tempel access_token yang diterbitkan SIMADU. Token dapat "
                "diambil melalui Postman menggunakan grant client_credentials."
            ),
        }
