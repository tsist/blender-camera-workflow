"""Windows Camera Workflow with a bundled Camera Live provider."""
bl_info = {"name": "Camera Workflow Windows", "author": "Camera Workflow contributors",
           "version": (0, 8, 3), "blender": (5, 2, 1), "location": "3D View > Sidebar > Camera Live",
           "description": "Review, diagnose and edit a verified copy of a saved camera scene", "category": "Camera"}

_owned_live = None

def register():
    global _owned_live
    import bpy
    from . import common, ui

    common.verify_package()
    live, _, _ = common.load_native()
    if hasattr(bpy.types.Scene, "camera_live_shots"):
        common.require(all(live.registered_class(cls) is cls for cls in live.CLASSES),
                       "Disable the other Camera Live provider before enabling this package")
    else:
        live.register()
        _owned_live = live
    try:
        ui.register()
    except Exception:
        if _owned_live is not None:
            _owned_live.unregister()
            _owned_live = None
        raise

def unregister():
    global _owned_live
    from . import ui

    ui.unregister()
    if _owned_live is not None:
        _owned_live.unregister()
        _owned_live = None
