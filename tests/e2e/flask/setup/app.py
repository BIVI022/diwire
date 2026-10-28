from flask import Flask

from diwire import Container, Injected, Scope, resolver_context
from diwire.integrations.flask import add_request_context
from tests.e2e.flask.setup.config import FlaskE2ESettings
from tests.e2e.flask.setup.services import CMService, RequestBasedService, latest_cleanup_path
from tests.e2e.runtime import assert_free_threaded_runtime

app = Flask(__name__)


@app.get("/health")
def health() -> str:
    return "OK"


@app.get("/services/request-based")
@resolver_context.inject(scope=Scope.REQUEST)
def request_based_service(service: Injected[RequestBasedService]) -> str:
    return service.work()


@app.get("/services/cm-service")
@resolver_context.inject(scope=Scope.REQUEST)
def cm_service(service: Injected[CMService]) -> str:
    return service.work()


@app.get("/services/cm-service/cleanup")
def cm_service_cleanup() -> str:
    cleanup_path = latest_cleanup_path()
    return f"Cleanup path: {cleanup_path}"


def main() -> None:
    assert_free_threaded_runtime()
    container = Container()
    add_request_context(container)
    container.add_context_manager(CMService, scope=Scope.REQUEST)

    settings = container.resolve(FlaskE2ESettings)
    app.run(host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
