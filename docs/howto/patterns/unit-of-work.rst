.. meta::
   :description: Unit-of-work pattern with diwire: share a scoped session across repositories/services and commit/rollback at the end of a scope.

Unit of work
============

If you have a transactional boundary (job, command, message, request), model it as a scope.

Typical setup
-------------

- Session/transaction: ``Lifetime.SCOPED``
- Repositories/services: ``Lifetime.TRANSIENT`` (they pull the current session from the scope)

Example (runnable)
------------------

The example below shares one request-scoped session across transient services
and repositories. Register the consumers with ``scope=Scope.REQUEST`` too.
Their default app scope cannot depend on a request-scoped session.

The in-memory session commits pending records when the request succeeds. It
discards them when a command raises an error. Both paths close the session.
The original error leaves the scope and is caught outside it.

A nested ``Scope.ACTION`` shares the request session. Leaving the action keeps
the transaction open until the owning request exits. A later request gets a
new session. Use a deeper scope for nested work; a request cannot contain
another request scope.

This session is a teaching example. For a real database, use its transaction
context manager and its commit, rollback and close operations.

.. code-block:: bash

   uv run python examples/ex_04_scopes_and_cleanup/05_unit_of_work.py

.. literalinclude:: ../../../examples/ex_04_scopes_and_cleanup/05_unit_of_work.py
   :language: python
   :class: diwire-example py-run

See :doc:`../examples/scopes` and :doc:`resources` for other cleanup patterns.
