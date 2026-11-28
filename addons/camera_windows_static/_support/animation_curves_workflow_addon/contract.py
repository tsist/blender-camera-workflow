"""Exception type retained for the read-only animation witness."""

class WorkflowError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}
