"""Windows host policy for the saved-copy transaction."""

if __package__:
    from ._support.blenderctl.host_compat import is_supported_host
else:
    from _support.blenderctl.host_compat import is_supported_host

RUNTIME_POLICY = {"minimum_version": "5.3.0"}
