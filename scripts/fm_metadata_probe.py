"""Windows FM27 metadata only: no remote memory reads or writes."""
import ctypes
from ctypes import wintypes as w
import json, os, sys
from contextlib import contextmanager

@contextmanager
def managed_handle(handle, close):
    try:
        yield handle
    finally:
        close(handle)

def report(probe):
    try:
        records = probe()
        return {"status": "ok" if records else "not_running", "processes": records}
    except OSError as exc:
        return {"status": "unavailable", "error": str(exc), "winerror": getattr(exc, "winerror", None)}

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),('flags',w.DWORD),('exe',w.WCHAR*260)]
class MODULEENTRY32(ctypes.Structure):
    _fields_ = [('size',w.DWORD),('module',w.DWORD),('pid',w.DWORD),('global_usage',w.DWORD),('process_usage',w.DWORD),('base',ctypes.c_void_p),('image_size',w.DWORD),('handle',w.HMODULE),('name',w.WCHAR*256),('path',w.WCHAR*260)]

def select_records(processes, modules):
    return [{'pid': p['pid'], 'image': p['image'], 'modules': [m for m in modules(p['pid']) if m['name'].lower() == 'game_plugin.dll']} for p in processes if os.path.basename(p['image']).lower() == 'fm.exe']

def check_enumeration_end(error):
    if error != 18:  # ERROR_NO_MORE_FILES is the only normal end.
        raise OSError(error, f'Toolhelp enumeration failed (Windows error {error})')

def enumerate_metadata():
    if os.name != 'nt': raise OSError('Windows only')
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD]; k.CreateToolhelp32Snapshot.restype=w.HANDLE
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]; k.OpenProcess.restype=w.HANDLE
    k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]; k.QueryFullProcessImageNameW.restype=w.BOOL
    k.CloseHandle.argtypes=[w.HANDLE]; k.CloseHandle.restype=w.BOOL
    for name, typ in [('Process32FirstW',PROCESSENTRY32),('Process32NextW',PROCESSENTRY32),('Module32FirstW',MODULEENTRY32),('Module32NextW',MODULEENTRY32)]:
        fn=getattr(k,name); fn.argtypes=[w.HANDLE,ctypes.POINTER(typ)]; fn.restype=w.BOOL
    invalid=ctypes.c_void_p(-1).value
    def snapshot(flags,pid):
        h=k.CreateToolhelp32Snapshot(flags,pid)
        if h == invalid: raise ctypes.WinError(ctypes.get_last_error())
        return h
    def modules(pid):
        h=snapshot(0x18,pid); out=[]
        with managed_handle(h, k.CloseHandle):
            e=MODULEENTRY32(); e.size=ctypes.sizeof(e); ok=k.Module32FirstW(h,ctypes.byref(e))
            while ok:
                out.append({'name':e.name,'path':e.path,'base':e.base,'size':e.image_size}); ok=k.Module32NextW(h,ctypes.byref(e))
            check_enumeration_end(ctypes.get_last_error())
        return out
    h=snapshot(2,0); processes=[]
    with managed_handle(h, k.CloseHandle):
        e=PROCESSENTRY32(); e.size=ctypes.sizeof(e); ok=k.Process32FirstW(h,ctypes.byref(e))
        while ok:
            if e.exe.lower() == 'fm.exe':
                ph=k.OpenProcess(0x1000,False,e.pid)
                if not ph: raise ctypes.WinError(ctypes.get_last_error())
                with managed_handle(ph, k.CloseHandle):
                    buf=ctypes.create_unicode_buffer(32768); n=w.DWORD(len(buf))
                    if not k.QueryFullProcessImageNameW(ph,0,buf,ctypes.byref(n)): raise ctypes.WinError(ctypes.get_last_error())
                    processes.append({'pid':e.pid,'image':buf.value})
            ok=k.Process32NextW(h,ctypes.byref(e))
        check_enumeration_end(ctypes.get_last_error())
    return select_records(processes,modules)

if __name__ == '__main__':
    result = report(enumerate_metadata)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    sys.exit(1 if result['status'] == 'unavailable' else 0)
