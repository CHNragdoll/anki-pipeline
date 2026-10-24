"""Advisory local volume capacity, including macOS reclaimable storage.

df reports unallocated blocks. macOS also reports capacity for important
usage. Neither value reserves space; write errors still roll back batches.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
import sys
import time

_CACHE = {}


def important_capacity(path):
    if sys.platform != 'darwin':
        return None
    path = str(Path(path).resolve(strict=True)); device = os.stat(path).st_dev
    cached = _CACHE.get(device)
    if cached and time.monotonic() - cached[0] < 60:
        return cached[1]
    foundation = ctypes.CDLL('/System/Library/Frameworks/Foundation.framework/Foundation')
    objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib'); pointer = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]; objc.objc_getClass.restype = pointer
    objc.sel_registerName.argtypes = [ctypes.c_char_p]; objc.sel_registerName.restype = pointer
    def send(obj, selector, result=pointer, types=(), args=()):
        method = ctypes.CFUNCTYPE(result, pointer, pointer, *types)(('objc_msgSend', objc))
        return method(obj, objc.sel_registerName(selector.encode()), *args)
    pool = send(objc.objc_getClass(b'NSAutoreleasePool'), 'new')
    try:
        string = send(objc.objc_getClass(b'NSString'), 'stringWithUTF8String:', types=(ctypes.c_char_p,), args=(path.encode(),))
        url = send(objc.objc_getClass(b'NSURL'), 'fileURLWithPath:', types=(pointer,), args=(string,))
        key = pointer.in_dll(foundation, 'NSURLVolumeAvailableCapacityForImportantUsageKey').value
        value = pointer(); error = pointer()
        ok = send(url, 'getResourceValue:forKey:error:', ctypes.c_bool,
                  (ctypes.POINTER(pointer), pointer, ctypes.POINTER(pointer)), (ctypes.byref(value), key, ctypes.byref(error)))
        result = send(value.value, 'longLongValue', ctypes.c_longlong) if ok and value.value else None
        _CACHE[device] = time.monotonic(), result
        return result
    finally:
        send(pool, 'drain', None)


def capacity_report(path):
    usage = shutil.disk_usage(path); important = important_capacity(path)
    return {'schema': 'study-catalog-capacity.v1', 'unallocated_bytes': usage.free,
            'available_for_important_usage_bytes': important,
            'advisory_available_bytes': max(usage.free, important or 0), 'reservation': False}
