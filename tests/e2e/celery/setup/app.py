from __future__ import annotations

from celery import Celery, Task

from diwire import Container, Injected, Lifetime, Scope, resolver_context
from tests.e2e.celery.setup.config import CeleryE2ESettings
from tests.e2e.celery.setup.services import AdderService, ScopedToken, build_scoped_token
from tests.e2e.runtime import assert_free_threaded_runtime

container = Container()
container.add(AdderService, provides=AdderService)
container.add_factory(
    build_scoped_token,
    provides=ScopedToken,
    scope=Scope.REQUEST,
    lifetime=Lifetime.SCOPED,
)

settings = container.resolve(CeleryE2ESettings)
celery_app = Celery(
    "diwire-celery-e2e",
    broker=settings.broker_url,
    backend=settings.result_backend,
)
celery_app.conf.update(
    task_default_queue=settings.queue,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)


@celery_app.task(name="tests.e2e.celery.tasks.add")
@resolver_context.inject(scope=Scope.REQUEST)
def add_task(left: int, right: int, adder: Injected[AdderService]) -> int:
    assert_free_threaded_runtime()
    return adder.add(left, right)


@celery_app.task(name="tests.e2e.celery.tasks.scope")
@resolver_context.inject(scope=Scope.REQUEST)
def scope_task(
    first: Injected[ScopedToken],
    second: Injected[ScopedToken],
) -> dict[str, str]:
    assert_free_threaded_runtime()
    return {"first": first.value, "second": second.value}


@celery_app.task(bind=True, name="tests.e2e.celery.tasks.bound")
@resolver_context.inject(scope=Scope.REQUEST)
def bound_task(task: Task, value: int, adder: Injected[AdderService]) -> str:
    assert_free_threaded_runtime()
    return f"{task.name}:{adder.add(value, 1)}"


app = celery_app

assert_free_threaded_runtime()
