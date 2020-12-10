import asyncio
import functools

from django.conf import settings
from django.core.handlers import base
from django.utils.module_loading import import_string
from django.core.handlers.exception import convert_exception_to_response
from django.core.handlers.base import logger
from django.core.exceptions import ImproperlyConfigured, MiddlewareNotUsed


async def send_async(signal, sender, **kwargs):
    for _, result in signal.send(sender, **kwargs):
        if result:
            await result


async def sync_to_async_view(func, *args, **kwargs):
    """ Asgiref function is unstable, so use simple executor."""
    return await asyncio.get_event_loop().run_in_executor(
        None, functools.partial(func, *args, **kwargs))


async def sync_to_async(func, *args, **kwargs):
    return func(*args, **kwargs)


class AsyncMiddlewareHandler(base.BaseHandler):
    sync_executor = staticmethod(sync_to_async)

    def load_middleware(self, is_async=False):
        """
        Populate middleware lists from settings.MIDDLEWARE.

        Must be called after the environment is fixed (see __call__ in
        subclasses). This version don't try to adapt sync-only middleware
        and raise exception if met.
        """
        self._view_middleware = []
        self._template_response_middleware = []
        self._exception_middleware = []
        if not is_async:
            raise ImproperlyConfigured('FastASGI async only.')
        get_response = self._get_response_async
        handler = convert_exception_to_response(get_response)
        for middleware_path in reversed(settings.MIDDLEWARE):
            middleware = import_string(middleware_path)
            middleware_can_async = getattr(middleware, 'async_capable', False)
            if not middleware_can_async:
                raise RuntimeError(
                    'Middleware %s must be async_capable set to True.' %
                    middleware_path
                )
            try:
                mw_instance = middleware(handler)
            except MiddlewareNotUsed as exc:
                if settings.DEBUG:
                    if str(exc):
                        logger.debug(
                            'MiddlewareNotUsed(%r): %s', middleware_path, exc)
                    else:
                        logger.debug('MiddlewareNotUsed: %r', middleware_path)
                continue

            if mw_instance is None:
                raise ImproperlyConfigured(
                    'Middleware factory %s returned None.' % middleware_path
                )

            if hasattr(mw_instance, 'process_view'):
                if not asyncio.iscoroutinefunction(mw_instance.process_view):
                    raise ImproperlyConfigured(
                        'Middleware %s process_view should be coroutine.' %
                        middleware_path
                    )
                self._view_middleware.insert(
                    0,
                    mw_instance.process_view,
                )
            if hasattr(mw_instance, 'process_template_response'):
                # TODO
                self._template_response_middleware.append(
                    mw_instance.process_template_response,
                )
            if hasattr(mw_instance, 'process_exception'):
                # TODO
                # The exception-handling stack is still always synchronous for
                # now, so adapt that way.
                self._exception_middleware.append(
                    mw_instance.process_exception)

            handler = convert_exception_to_response(mw_instance)
        # We only assign to this when initialization is complete as it is used
        # as a flag for initialization being complete.
        self._middleware_chain = handler

    def adapt_method_mode(
        self, is_async, method, method_is_async=None, debug=False, name=None,
    ):
        raise ImproperlyConfigured(
            'ASGI implementation do not adapt sync methods')

    async def _get_response_async(self, request):
        """
        Resolve and call the view, then apply view, exception, and
        template_response middleware. This method is everything that happens
        inside the request/response middleware.
        """
        response = None
        callback, callback_args, callback_kwargs = self.resolve_request(
            request)

        # Apply view middleware.
        for middleware_method in self._view_middleware:
            response = await middleware_method(
                request, callback, callback_args, callback_kwargs)
            if response:
                break

        if response is None:
            wrapped_callback = self.make_view_atomic(callback)
            # If it is a synchronous view, run it in a subthread
            try:
                if asyncio.iscoroutinefunction(wrapped_callback):
                    response = await wrapped_callback(
                        request, *callback_args, **callback_kwargs)
                else:
                    #response = wrapped_callback(request, *callback_args, **callback_kwargs)
                    response = await sync_to_async_view(
                        wrapped_callback,
                        request, *callback_args, **callback_kwargs)
            except Exception as e:
                # TODO
                response = await self.sync_executor(
                    self.process_exception_by_middleware, e, request
                )
                if response is None:
                    raise

        # Complain if the view returned None or an uncalled coroutine.
        self.check_response(response, callback)

        # If the response supports deferred rendering, apply template
        # response middleware and then render the response
        if hasattr(response, 'render') and callable(response.render):
            # TODO: rendering
            for middleware_method in self._template_response_middleware:
                response = await middleware_method(request, response)
                # Complain if the template response middleware returned None or
                # an uncalled coroutine.
                self.check_response(
                    response,
                    middleware_method,
                    name='%s.process_template_response' % (
                        middleware_method.__self__.__class__.__name__,
                    )
                )
            try:
                if asyncio.iscoroutinefunction(response.render):
                    response = await response.render()
                else:
                    response = await self.sync_executor(response.render)
            except Exception as e:
                response = await self.sync_executor(
                    self.process_exception_by_middleware, e, request
                )
                if response is None:
                    raise

        # Make sure the response is not a coroutine
        if asyncio.iscoroutine(response):
            raise RuntimeError('Response is still a coroutine.')
        return response
