"""Windows Camera Workflow with a bundled Camera Live provider."""
bl_info = {"name": "Camera Workflow", "author": "Camera Workflow contributors",
           "version": (0, 8, 3), "blender": (5, 2, 1), "location": "3D View > Sidebar > Camera Live",
           "description": "Windows camera workflows and Linux 5.3 enrolled static-camera verified copies", "category": "Camera"}

_owned_live = None

def register():
    global _owned_live
    import sys
    if sys.platform.startswith("linux"):
        from . import linux_panel
        import bpy
        from . import shot_ab
        # Refuse existing external owners before registering even the first class.
        for cls in shot_ab.classes:
            if getattr(bpy.types,cls.__name__,None) is not None:
                raise RuntimeError('Camera A/B type already has an owner: '+cls.__name__)
        linux_panel.register()
        try:shot_ab.register()
        except Exception:
            for cls in reversed(shot_ab.classes):
                owner=getattr(bpy.types,cls.__name__,None)
                if owner is cls:bpy.utils.unregister_class(cls)
            linux_panel.unregister()
            raise
        return
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
    import sys
    if sys.platform.startswith("linux"):
        from . import linux_panel
        from . import shot_ab
        shot_ab.unregister()
        return linux_panel.unregister()
    from . import ui

    ui.unregister()
    if _owned_live is not None:
        _owned_live.unregister()
        _owned_live = None
