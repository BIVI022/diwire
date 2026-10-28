"""Share one transaction across transient services and repositories.

Commit on success, roll back on error, and close at the request boundary.
This in-memory session shows the wiring without a database dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import TracebackType

from diwire import Container, Lifetime, Scope


@dataclass
class Store:
    records: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)


class Session:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.pending: list[str] = []
        self.closed = False

    # Keep this Python 3.10 example free of a typing-extensions runtime dependency.
    def __enter__(self) -> Session:  # noqa: PYI034
        self.store.events.append("open")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                self.store.records.extend(self.pending)
                self.store.events.append("commit")
            else:
                self.store.events.append("rollback")
            self.pending.clear()
        finally:
            self.closed = True
            self.store.events.append("close")


@dataclass
class Repository:
    session: Session

    def save(self, record: str) -> None:
        self.session.pending.append(record)


@dataclass
class Service:
    session: Session
    repository: Repository

    def execute(self, record: str) -> None:
        self.repository.save(record)


class CommandError(Exception):
    pass


def main() -> None:
    store = Store()
    container = Container()
    container.add_instance(store)
    container.add_context_manager(Session, scope=Scope.REQUEST, lifetime=Lifetime.SCOPED)
    container.add(Repository, scope=Scope.REQUEST, lifetime=Lifetime.TRANSIENT)
    container.add(Service, scope=Scope.REQUEST, lifetime=Lifetime.TRANSIENT)

    with container.enter_scope(Scope.REQUEST) as request:
        service = request.resolve(Service)
        other = request.resolve(Service)
        transient_consumers = service is not other and service.repository is not other.repository
        shared_session = service.session is service.repository.session is other.session
        service.execute("accepted")
        pending_until_exit = not store.records

        with request.enter_scope(Scope.ACTION) as action:
            nested = action.resolve(Service)
            nested_shares_session = nested is not service and nested.session is service.session
        action_keeps_transaction_open = not service.session.closed and store.events == ["open"]

    committed_and_closed = store.records == ["accepted"] and service.session.closed
    original_error = CommandError("Command failed")
    error_propagated = False
    try:
        with container.enter_scope(Scope.REQUEST) as request:
            failed = request.resolve(Service)
            fresh_session = failed.session is not service.session
            failed.execute("rejected")
            raise original_error
    except CommandError as error:
        error_propagated = error is original_error

    rolled_back_and_closed = store.records == ["accepted"] and failed.session.closed
    lifecycle = store.events == ["open", "commit", "close", "open", "rollback", "close"]
    print(f"transient_consumers={transient_consumers}")  # => transient_consumers=True
    print(f"shared_session={shared_session}")  # => shared_session=True
    print(f"pending_until_exit={pending_until_exit}")  # => pending_until_exit=True
    print(f"nested_shares_session={nested_shares_session}")  # => nested_shares_session=True
    print(
        f"action_keeps_transaction_open={action_keeps_transaction_open}"
    )  # => action_keeps_transaction_open=True
    print(f"committed_and_closed={committed_and_closed}")  # => committed_and_closed=True
    print(f"fresh_session={fresh_session}")  # => fresh_session=True
    print(f"error_propagated={error_propagated}")  # => error_propagated=True
    print(f"rolled_back_and_closed={rolled_back_and_closed}")  # => rolled_back_and_closed=True
    print(f"lifecycle={lifecycle}")  # => lifecycle=True


if __name__ == "__main__":
    main()
