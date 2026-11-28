"""Windows Camera Workflow with a bundled Camera Live provider."""
bl_info = {"name": "镜头工作台", "author": "Camera Workflow contributors",
           "version": (1, 0, 0), "blender": (5, 3, 0), "location": "3D 视口侧栏",
           "description": "编辑镜头表、预演运镜与核验镜头副本", "category": "Camera"}

_owned_live = None

def register():
    global _owned_live
    import bpy
    from . import artist_ui, common, ui

    common.verify_package()
    live, _, _ = common.load_native()
    if hasattr(bpy.types.Scene, "camera_live_shots"):
        common.require(all(live.registered_class(cls) is cls for cls in live.CLASSES),
                       "Disable the other Camera Live provider before enabling this package")
    else:
        live.register()
        _owned_live = live
    try:
        if _owned_live is live and live.registered_class(live.CLREBUILD_PT_preview) is live.CLREBUILD_PT_preview:
            bpy.utils.unregister_class(live.CLREBUILD_PT_preview)
        ui.register()
        try:
            artist_ui.register()
        except Exception:
            ui.unregister()
            raise
    except Exception:
        if _owned_live is not None:
            _owned_live.unregister()
            _owned_live = None
        raise

def unregister():
    global _owned_live
    from . import artist_ui, ui

    ui.unregister()
    artist_ui.unregister()
    if _owned_live is not None:
        _owned_live.unregister()
        _owned_live = None
