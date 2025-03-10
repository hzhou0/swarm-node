# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc
import warnings

import networking_pb2 as networking__pb2

GRPC_GENERATED_VERSION = '1.70.0'
GRPC_VERSION = grpc.__version__
_version_not_supported = False

try:
    from grpc._utilities import first_version_is_lower
    _version_not_supported = first_version_is_lower(GRPC_VERSION, GRPC_GENERATED_VERSION)
except ImportError:
    _version_not_supported = True

if _version_not_supported:
    raise RuntimeError(
        f'The grpc package installed is at version {GRPC_VERSION},'
        + f' but the generated code in networking_pb2_grpc.py depends on'
        + f' grpcio>={GRPC_GENERATED_VERSION}.'
        + f' Please upgrade your grpc module to grpcio>={GRPC_GENERATED_VERSION}'
        + f' or downgrade your generated code using grpcio-tools<={GRPC_VERSION}.'
    )


class WebrtcProxyStub(object):
    """Missing associated documentation comment in .proto file."""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.Connect = channel.stream_stream(
                '/networking.WebrtcProxy/Connect',
                request_serializer=networking__pb2.Mutation.SerializeToString,
                response_deserializer=networking__pb2.Event.FromString,
                _registered_method=True)


class WebrtcProxyServicer(object):
    """Missing associated documentation comment in .proto file."""

    def Connect(self, request_iterator, context):
        """Streams all fields in `Mutation` and returns all fields in `Event`
        """
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_WebrtcProxyServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'Connect': grpc.stream_stream_rpc_method_handler(
                    servicer.Connect,
                    request_deserializer=networking__pb2.Mutation.FromString,
                    response_serializer=networking__pb2.Event.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'networking.WebrtcProxy', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers('networking.WebrtcProxy', rpc_method_handlers)


 # This class is part of an EXPERIMENTAL API.
class WebrtcProxy(object):
    """Missing associated documentation comment in .proto file."""

    @staticmethod
    def Connect(request_iterator,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.stream_stream(
            request_iterator,
            target,
            '/networking.WebrtcProxy/Connect',
            networking__pb2.Mutation.SerializeToString,
            networking__pb2.Event.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)
