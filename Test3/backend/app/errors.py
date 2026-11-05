class Test3Error(Exception):
    code = "TEST3_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class IllegalTransition(Test3Error):
    code = "ILLEGAL_TRANSITION"


class AgentOutputError(Test3Error):
    code = "AGENT_OUTPUT_ERROR"


class ConfigError(Test3Error):
    code = "CONFIG_ERROR"


class RevisionConflict(Test3Error):
    code = "REVISION_CONFLICT"


class WriteDenied(Test3Error):
    code = "WRITE_DENIED"


class CommandDenied(Test3Error):
    code = "COMMAND_DENIED"


class BudgetExceeded(Test3Error):
    code = "BUDGET_EXCEEDED"


class ReplayMissing(Test3Error):
    code = "REPLAY_MISSING"


class ValidationFailed(Test3Error):
    code = "VALIDATION_FAILED"
