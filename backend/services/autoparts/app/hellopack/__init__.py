"""HelloPack: minimal domain package example.

Demonstrates the per-domain layout used across the service: a small service
class (``HelloPackService``) exposed through a resource router
(``app.api.v1.hellopack``) and covered by a test. New domain packages should
copy this shape: package under ``app/``, service in ``app/services`` or in
the package itself, router in ``app/api/v1``, test in ``tests/``.
"""

from app.hellopack.service import HelloPackService

__all__ = ["HelloPackService"]
