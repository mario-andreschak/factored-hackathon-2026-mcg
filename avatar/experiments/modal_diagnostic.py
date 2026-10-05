"""Local-only, allowlisted Modal diagnostics. Never serialize provider messages."""
from personaplex_modal import diagnostic as legacy_diagnostic


GRPC_CODES = {
    'CANCELLED': 'operation_cancelled',
    'UNKNOWN': 'modal_api_failed',
    'INVALID_ARGUMENT': 'modal_request_rejected',
    'DEADLINE_EXCEEDED': 'deadline_exceeded',
    'NOT_FOUND': 'modal_resource_unavailable',
    'ALREADY_EXISTS': 'modal_resource_conflict',
    'PERMISSION_DENIED': 'modal_permission_denied',
    'RESOURCE_EXHAUSTED': 'modal_capacity_unavailable',
    'FAILED_PRECONDITION': 'modal_precondition_failed',
    'ABORTED': 'modal_operation_aborted',
    'OUT_OF_RANGE': 'modal_request_rejected',
    'UNIMPLEMENTED': 'modal_api_unsupported',
    'INTERNAL': 'modal_api_failed',
    'UNAVAILABLE': 'modal_api_unavailable',
    'DATA_LOSS': 'modal_api_failed',
    'UNAUTHENTICATED': 'modal_auth_unavailable',
}
MODAL_CODES = {
    'ClientClosed': 'client_context_closed',
    'NestedEventLoops': 'client_context_mismatch',
    'AssertionError': 'client_invariant_failed',
    'AlreadyExistsError': 'modal_resource_conflict',
    'AuthError': 'modal_auth_unavailable',
    'InternalError': 'modal_api_failed',
    'InvalidError': 'modal_request_rejected',
    'ConflictError': 'modal_precondition_failed',
    'DataLossError': 'modal_api_failed',
    'NotFoundError': 'modal_resource_unavailable',
    'PermissionDeniedError': 'modal_permission_denied',
    'ResourceExhaustedError': 'modal_capacity_unavailable',
    'ServiceError': 'modal_api_unavailable',
    'UnimplementedError': 'modal_api_unsupported',
    'StreamTerminatedError': 'transport_unavailable',
    'ProtocolError': 'transport_unavailable',
}


def diagnostic(error: BaseException, stage: str) -> dict:
    """Inspect only fixed enum/class names for transport errors, never str(error)."""
    name = type(error).__name__
    if name == 'GRPCError' or name in MODAL_CODES:
        # Modal 1.5 migrates gRPC failures to named Modal exceptions. Its private
        # enum avoids a deprecated status property that would emit warnings.
        status_value = getattr(error, '_grpc_status', None)
        if status_value is None and name == 'GRPCError': status_value = getattr(error, 'status', None)
        status = getattr(status_value, 'name', None)
        result = {'stage': stage, 'error_class': name,
                  'failure_code': GRPC_CODES.get(status, MODAL_CODES.get(name, 'modal_api_failed'))}
        if status in GRPC_CODES:
            result['grpc_status'] = status
        return result
    if name in {'AttributeError', 'TypeError', 'ConnectionError', 'CancelledError'}:
        return {'stage': stage, 'error_class': name,
                'failure_code': {'AttributeError': 'client_adapter_mismatch',
                                 'TypeError': 'client_adapter_mismatch',
                                 'ConnectionError': 'transport_unavailable',
                                 'CancelledError': 'operation_cancelled'}[name]}
    return legacy_diagnostic(error, stage)
