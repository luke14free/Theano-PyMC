"""Utility functions that only depend on the standard library."""


import inspect
import os
import struct
import subprocess
import sys
import traceback
import warnings
from collections import OrderedDict
from collections.abc import Callable
from functools import wraps


__all__ = [
    "cmp",
    "get_unbound_function",
    "maybe_add_to_os_environ_pathlist",
    "DefaultOrderedDict",
    "deprecated",
    "subprocess_Popen",
    "call_subprocess_Popen",
    "output_subprocess_Popen",
    "LOCAL_BITWIDTH",
    "PYTHON_INT_BITWIDTH",
]


__excepthooks = []


LOCAL_BITWIDTH = struct.calcsize("P") * 8
"""
32 for 32bit arch, 64 for 64bit arch.
By "architecture", we mean the size of memory pointers (size_t in C),
*not* the size of long int, as it can be different.

Note that according to Python documentation, `platform.architecture()` is
not reliable on OS X with universal binaries.
Also, sys.maxsize does not exist in Python < 2.6.
'P' denotes a void*, and the size is expressed in bytes.
"""

PYTHON_INT_BITWIDTH = struct.calcsize("l") * 8
"""
The bit width of Python int (C long int).

Note that it can be different from the size of a memory pointer.
'l' denotes a C long int, and the size is expressed in bytes.
"""


def __call_excepthooks(type, value, trace):
    """
    This function is meant to replace excepthook and do some
    special work if the exception value has a __thunk_trace__
    field.
    In that case, it retrieves the field, which should
    contain a trace as returned by L{traceback.extract_stack},
    and prints it out on L{stderr}.

    The normal excepthook is then called.

    Parameters:
    ----------
    type
        Exception class
    value
        Exception instance
    trace
        Traceback object

    Notes
    -----
    This hook replaced in testing, so it does not run.

    """
    for hook in __excepthooks:
        hook(type, value, trace)
    sys.__excepthook__(type, value, trace)


def add_excepthook(hook):
    """Adds an excepthook to a list of excepthooks that are called
    when an unhandled exception happens.

    See https://docs.python.org/3/library/sys.html#sys.excepthook for signature info.
    """
    __excepthooks.append(hook)
    sys.excepthook = __call_excepthooks


def exc_message(e):
    """
    In python 3.x, when an exception is reraised it saves original
    exception in its args, therefore in order to find the actual
    message, we need to unpack arguments recursively.
    """
    msg = e.args[0]
    if isinstance(msg, Exception):
        return exc_message(msg)
    return msg


def cmp(x, y):
    """Return -1 if x < y, 0 if x == y, 1 if x > y."""
    return (x > y) - (x < y)


def get_unbound_function(unbound):
    # Op.make_thunk isn't bound, so don't have a __func__ attr.
    # But bound method, have a __func__ method that point to the
    # not bound method. That is what we want.
    if hasattr(unbound, "__func__"):
        return unbound.__func__
    return unbound


class DefaultOrderedDict(OrderedDict):
    def __init__(self, default_factory=None, *a, **kw):
        if default_factory is not None and not isinstance(default_factory, Callable):
            raise TypeError("first argument must be callable")
        OrderedDict.__init__(self, *a, **kw)
        self.default_factory = default_factory

    def __getitem__(self, key):
        try:
            return OrderedDict.__getitem__(self, key)
        except KeyError:
            return self.__missing__(key)

    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        self[key] = value = self.default_factory()
        return value

    def __reduce__(self):
        if self.default_factory is None:
            args = tuple()
        else:
            args = (self.default_factory,)
        return type(self), args, None, None, list(self.items())

    def copy(self):
        return self.__copy__()

    def __copy__(self):
        return type(self)(self.default_factory, self)


def maybe_add_to_os_environ_pathlist(var, newpath):
    """Unfortunately, Conda offers to make itself the default Python
    and those who use it that way will probably not activate envs
    correctly meaning e.g. mingw-w64 g++ may not be on their PATH.

    This function ensures that, if `newpath` is an absolute path,
    and it is not already in os.environ[var] it gets added to the
    front.

    The reason we check first is because Windows environment vars
    are limited to 8191 characters and it is easy to hit that.

    `var` will typically be 'PATH'."""

    import os

    if os.path.isabs(newpath):
        try:
            oldpaths = os.environ[var].split(os.pathsep)
            if newpath not in oldpaths:
                newpaths = os.pathsep.join([newpath] + oldpaths)
                os.environ[var] = newpaths
        except Exception:
            pass


def deprecated(message: str = ""):
    """
    This is a decorator which can be used to mark functions
    as deprecated. It will result in a warning being emitted
    when the function is used first time and filter is set for show DeprecationWarning.

    Taken from https://stackoverflow.com/a/40899499/4473230
    """

    def decorator_wrapper(func):
        @wraps(func)
        def function_wrapper(*args, **kwargs):
            current_call_source = "|".join(
                traceback.format_stack(inspect.currentframe())
            )
            if current_call_source not in function_wrapper.last_call_source:
                warnings.warn(
                    "Function {} is now deprecated! {}".format(func.__name__, message),
                    category=DeprecationWarning,
                    stacklevel=2,
                )
                function_wrapper.last_call_source.add(current_call_source)

            return func(*args, **kwargs)

        function_wrapper.last_call_source = set()

        return function_wrapper

    return decorator_wrapper


def subprocess_Popen(command, **params):
    """
    Utility function to work around windows behavior that open windows.

    :see: call_subprocess_Popen and output_subprocess_Popen
    """
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        try:
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        except AttributeError:
            startupinfo.dwFlags |= subprocess._subprocess.STARTF_USESHOWWINDOW

        # Anaconda for Windows does not always provide .exe files
        # in the PATH, they also have .bat files that call the corresponding
        # executable. For instance, "g++.bat" is in the PATH, not "g++.exe"
        # Unless "shell=True", "g++.bat" is not executed when trying to
        # execute "g++" without extensions.
        # (Executing "g++.bat" explicitly would also work.)
        params["shell"] = True
        # "If shell is True, it is recommended to pass args as a string rather than as a sequence." (cite taken from https://docs.python.org/2/library/subprocess.html#frequently-used-arguments)
        # In case when command arguments have spaces, passing a command as a list will result in incorrect arguments break down, and consequently
        # in "The filename, directory name, or volume label syntax is incorrect" error message.
        # Passing the command as a single string solves this problem.
        if isinstance(command, list):
            command = " ".join(command)

    # Using the dummy file descriptors below is a workaround for a
    # crash experienced in an unusual Python 2.4.4 Windows environment
    # with the default None values.
    stdin = None
    if "stdin" not in params:
        stdin = open(os.devnull)
        params["stdin"] = stdin.fileno()

    try:
        proc = subprocess.Popen(command, startupinfo=startupinfo, **params)
    finally:
        if stdin is not None:
            stdin.close()
    return proc


def call_subprocess_Popen(command, **params):
    """
    Calls subprocess_Popen and discards the output, returning only the
    exit code.
    """
    if "stdout" in params or "stderr" in params:
        raise TypeError("don't use stderr or stdout with call_subprocess_Popen")
    with open(os.devnull, "wb") as null:
        # stdin to devnull is a workaround for a crash in a weird Windows
        # environment where sys.stdin was None
        params.setdefault("stdin", null)
        params["stdout"] = null
        params["stderr"] = null
        p = subprocess_Popen(command, **params)
        returncode = p.wait()
    return returncode


def output_subprocess_Popen(command, **params):
    """
    Calls subprocess_Popen, returning the output, error and exit code
    in a tuple.
    """
    if "stdout" in params or "stderr" in params:
        raise TypeError("don't use stderr or stdout with output_subprocess_Popen")
    params["stdout"] = subprocess.PIPE
    params["stderr"] = subprocess.PIPE
    p = subprocess_Popen(command, **params)
    # we need to use communicate to make sure we don't deadlock around
    # the stdout/stderr pipe.
    out = p.communicate()
    return out + (p.returncode,)
