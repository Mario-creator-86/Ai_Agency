from app.providers.media_http import MediaProviderError, MediaProviderNotConfigured


class RunPodDisabled(MediaProviderNotConfigured):
    pass


class RunPodProtocolError(MediaProviderError):
    pass


class IdempotencyConflict(MediaProviderError):
    pass


class SubmissionUncertain(MediaProviderError):
    """A durable intent has no verified remote id; never automatically submit it again."""


class InfrastructureDisabled(MediaProviderError):
    pass
