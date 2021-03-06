"""
Wrapper around scrypt.
"""
from __future__ import absolute_import, division

from json import dumps, loads
from os import urandom
from scrypt import hash
from twisted.internet import defer, reactor
from twisted.internet.threads import deferToThreadPool
from twisted.python import threadpool

from base64 import b64encode, b64decode


STORAGESEPARATOR = b"$"

class Wrapper(object):
    urandom = staticmethod(urandom)

    def __init__(self, reactor, threadPool, saltLength, **params):
        self.reactor = reactor
        self.threadPool = threadPool
        self.saltLength = saltLength
        self._params = params


    def _deferToThread(self, f, *a, **kw):
        """Defers to the thread pool.

        If the thread pool has not been started yet, starts the thread
        pool and schedules it to be stopped before the reactor stops.

        """
        if not self.threadPool.started:
            self.threadPool.start()
            self.reactor.addSystemEventTrigger(
                "before", "shutdown", self.threadPool.stop)

        return deferToThreadPool(self.reactor, self.threadPool, f, *a, **kw)


    def checkPassword(self, stored, provided):
        """Checks that the stored key was computed from the provided password.

        Returns a deferred that will fire with ``True``, if the
        password was correct, or ``False`` otherwise. The deferred
        will fail with ValueError if the stored value was not
        recognized as a txscrypt value.

        """
        if not isinstance(stored, bytes) or not isinstance(provided, bytes):
            return defer.fail(
                ValueError("Only able to compute hashes of bytes."))

        try:
            comment, encodedParams, encodedKey, encodedSalt = stored.split(
                STORAGESEPARATOR)
        except ValueError:
            return defer.fail(ValueError("Invalid number of fields"))

        if comment != b"txscrypt":
            return defer.fail(ValueError("Missing txscrypt prefix"))

        params = loads(encodedParams.decode("ascii"))
        key, salt = [b64decode(s) for s in [encodedKey, encodedSalt]]
        d = self._deferToThread(hash, provided, salt, **params)
        return d.addCallback(key.__eq__)


    def computeKey(self, password):
        """Computes a key from the password using a secure key derivation
        function.
        """
        if not isinstance(password, bytes):
            return defer.fail(
                ValueError("Only able to compute hashes of bytes."))

        salt = self.urandom(self.saltLength)
        d = self._deferToThread(hash, password, salt, **self._params)
        return d.addCallback(self._encode, salt)


    def _encode(self, key, salt):
        """Encodes the computed key, salt and parameters.

        """
        key, salt = [b64encode(s).strip() for s in [key, salt]]
        # The parameters will always be ASCII encodable.
        params = dumps(self._params).encode("ascii")
        return b"txscrypt$" + STORAGESEPARATOR.join([params, key, salt])



DEFAULT_SALT_LENGTH = 256 // 8
DEFAULT_ITERATIONS = 2 ** 15

_pool = threadpool.ThreadPool()
_wrapper = Wrapper(reactor, _pool, DEFAULT_SALT_LENGTH, N=DEFAULT_ITERATIONS)
computeKey  = _wrapper.computeKey
checkPassword = _wrapper.checkPassword

# Keep a reference to the reactor thread pool so I can unit test that
# the module-level instance isn't using it, despite t.trial
# shennanigans.
_reactorPool = reactor.getThreadPool()
