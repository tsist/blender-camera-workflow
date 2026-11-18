"""Narrow disabled-idle reload, no cancellation, resource release or foreign writes."""
import importlib
from pathlib import Path
import sys
import types
from .reload_identity import verify_generation

_failed = False
PACKAGE = 'camera_live_rebuilt'

def require(ok, message):
    if not ok:
        raise RuntimeError('Camera Live reload refused: ' + message)

def module(name, root):
    item = sys.modules.get(PACKAGE + '.' + name)
    require(isinstance(item, types.ModuleType) and item.__name__ == PACKAGE + '.' + name,
            name + ' module identity unavailable')
    path = Path(getattr(item, '__file__', ''))
    require(not path.is_symlink() and path.resolve() == (root / (name + '.py')).resolve(),
            name + ' module path differs')
    return item

def prepare_import(ns):
    global _failed
    require(ns.get('__name__') == PACKAGE, 'unexpected package')
    require(not _failed, 'incomplete refresh; restart Blender before enabling')
    if 'bl_info' not in ns:
        require(not any(n.startswith(PACKAGE + '.') and n not in (PACKAGE + '.reload_guard', PACKAGE + '.reload_identity') for n in sys.modules),
                'orphaned own submodules remain; restart Blender before enabling')
        return
    require(tuple(ns.get('bl_info', {}).get('version', ())) in ((0,6,0),(0,7,0),(0,7,1),(0,7,2)),
            'unsupported source version')
    require(ns.get('_copy_enabled') is False, 'still enabled; disable only after work is idle')
    require(ns.get('_registered') == [] and ns.get('_scene_properties') == {}, 'RNA ownership retained')
    lookup=ns.get('registered_class');classes=ns.get('CLASSES')
    require(callable(lookup) and classes and all(lookup(c) is None for c in classes), 'RNA identifier occupied')
    bpy=ns.get('bpy')
    require(bpy is not None and all(not hasattr(bpy.types.Scene,n) for n in ns.get('SCENE_PROPERTIES', ())),
            'scene descriptors remain')
    for name in ('_timer','_copy_timer','_copy_pending','_candidate','_compare_side','_author_owner','_author_enum_cache'):
        require(name in ns and ns[name] is None, 'retained ' + name)
    require(ns.get('_copy_ready') is None, 'retained _copy_ready')
    preview=ns.get('_preview')
    require(preview is not None and preview.lease is None and preview.state == 'IDLE', 'preview lease/state retained')
    root=Path(ns['__file__']).resolve().parent
    service=module('copy_service',root)
    require(ns.get('copy_service') is service, 'copy service owner differs')
    slot=sys.modules.get(service.REGISTRY_NAME)
    require(isinstance(slot,types.ModuleType) and getattr(slot,'marker',None)==service.REGISTRY_MARKER
            and getattr(slot,'version',None)==1 and type(getattr(slot,'epoch',None)) is int and slot.epoch>=0,
            'persistent copy registry identity differs')
    require(hasattr(slot,'process') and slot.process is None, 'copy process running or awaiting collection')
    for observer in vars(slot).values():
        alive=getattr(observer, 'is_alive', None)
        require(not callable(alive) or not alive(), 'copy observer still alive')
    try:
        verify_generation(ns, root)
    except BaseException as exc:
        _failed=True
        raise RuntimeError('Camera Live mixed/unknown generation; keep disabled and restart Blender') from exc
    # Only changed code and its direct aliases. Persistent service/runtime untouched.
    targets=[module(name,root) for name in ('core','adapter','workbench')]
    for item in targets:
        compile(Path(item.__file__).read_bytes(),item.__file__,'exec')
    try:
        importlib.invalidate_caches()
        for item in targets:
            importlib.reload(item)
    except BaseException as exc:
        _failed=True
        raise RuntimeError('Camera Live reload incomplete; keep disabled and restart Blender') from exc
