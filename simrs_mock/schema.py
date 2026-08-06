from drf_spectacular.extensions import OpenApiAuthenticationExtension


class MockBearerScheme(OpenApiAuthenticationExtension):
    target_class = "simrs_mock.authentication.MockBearerAuthentication"
    name = "MockSimrsBearer"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "description": "Development token: mock-simrs-token. Production menggunakan token SIMADU dengan scope simrs.indicators.read.",
        }
