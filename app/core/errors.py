class PipelineError(Exception):
    """Safe, content-free message that may be returned to a client."""


class InputError(PipelineError):
    pass


class ParserError(PipelineError):
    pass


class ExtractionError(PipelineError):
    pass


class RagFlowError(PipelineError):
    pass
