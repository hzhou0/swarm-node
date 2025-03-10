from typing import (
    ClassVar as _ClassVar,
    Iterable as _Iterable,
    Mapping as _Mapping,
    Optional as _Optional,
    Union as _Union,
)

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

DESCRIPTOR: _descriptor.FileDescriptor

class NamedTrack(_message.Message):
    __slots__ = ("track_id", "stream_id", "mime_type")
    TRACK_ID_FIELD_NUMBER: _ClassVar[int]
    STREAM_ID_FIELD_NUMBER: _ClassVar[int]
    MIME_TYPE_FIELD_NUMBER: _ClassVar[int]
    track_id: str
    stream_id: str
    mime_type: str

    def __init__(
        self,
        track_id: _Optional[str] = ...,
        stream_id: _Optional[str] = ...,
        mime_type: _Optional[str] = ...,
    ) -> None: ...

class WebrtcOffer(_message.Message):
    __slots__ = (
        "src_uuid",
        "sdp",
        "type",
        "local_tracks",
        "local_tracks_set",
        "remote_tracks",
        "remote_tracks_set",
        "datachannel",
    )
    SRC_UUID_FIELD_NUMBER: _ClassVar[int]
    SDP_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    LOCAL_TRACKS_FIELD_NUMBER: _ClassVar[int]
    LOCAL_TRACKS_SET_FIELD_NUMBER: _ClassVar[int]
    REMOTE_TRACKS_FIELD_NUMBER: _ClassVar[int]
    REMOTE_TRACKS_SET_FIELD_NUMBER: _ClassVar[int]
    DATACHANNEL_FIELD_NUMBER: _ClassVar[int]
    src_uuid: str
    sdp: str
    type: str
    local_tracks: _containers.RepeatedCompositeFieldContainer[NamedTrack]
    local_tracks_set: bool
    remote_tracks: _containers.RepeatedCompositeFieldContainer[NamedTrack]
    remote_tracks_set: bool
    datachannel: bool

    def __init__(
        self,
        src_uuid: _Optional[str] = ...,
        sdp: _Optional[str] = ...,
        type: _Optional[str] = ...,
        local_tracks: _Optional[_Iterable[_Union[NamedTrack, _Mapping]]] = ...,
        local_tracks_set: bool = ...,
        remote_tracks: _Optional[_Iterable[_Union[NamedTrack, _Mapping]]] = ...,
        remote_tracks_set: bool = ...,
        datachannel: bool = ...,
    ) -> None: ...

class DataChannel(_message.Message):
    __slots__ = ("src_uuid", "dest_uuid")
    SRC_UUID_FIELD_NUMBER: _ClassVar[int]
    DEST_UUID_FIELD_NUMBER: _ClassVar[int]
    src_uuid: str
    dest_uuid: str
    def __init__(self, src_uuid: _Optional[str] = ..., dest_uuid: _Optional[str] = ...) -> None: ...

class DataTransmission(_message.Message):
    __slots__ = ("channel", "payload")
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    channel: DataChannel
    payload: bytes

    def __init__(
        self,
        channel: _Optional[_Union[DataChannel, _Mapping]] = ...,
        payload: _Optional[bytes] = ...,
    ) -> None: ...

class MediaChannel(_message.Message):
    __slots__ = ("src_uuid", "dest_uuid", "track", "localhost_port", "close")
    SRC_UUID_FIELD_NUMBER: _ClassVar[int]
    DEST_UUID_FIELD_NUMBER: _ClassVar[int]
    TRACK_FIELD_NUMBER: _ClassVar[int]
    LOCALHOST_PORT_FIELD_NUMBER: _ClassVar[int]
    CLOSE_FIELD_NUMBER: _ClassVar[int]
    src_uuid: str
    dest_uuid: str
    track: NamedTrack
    localhost_port: int
    close: bool

    def __init__(
        self,
        src_uuid: _Optional[str] = ...,
        dest_uuid: _Optional[str] = ...,
        track: _Optional[_Union[NamedTrack, _Mapping]] = ...,
        localhost_port: _Optional[int] = ...,
        close: bool = ...,
    ) -> None: ...

class Stats(_message.Message):
    __slots__ = (
        "dest_uuid",
        "cumulative_rtt",
        "current_rtt",
        "outgoing_bitrate",
        "incoming_bitrate",
        "protocol",
        "type",
    )

    class ICEType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        Unknown: _ClassVar[Stats.ICEType]
        Host: _ClassVar[Stats.ICEType]
        Srflx: _ClassVar[Stats.ICEType]
        Prflx: _ClassVar[Stats.ICEType]
        Relay: _ClassVar[Stats.ICEType]
    Unknown: Stats.ICEType
    Host: Stats.ICEType
    Srflx: Stats.ICEType
    Prflx: Stats.ICEType
    Relay: Stats.ICEType
    DEST_UUID_FIELD_NUMBER: _ClassVar[int]
    CUMULATIVE_RTT_FIELD_NUMBER: _ClassVar[int]
    CURRENT_RTT_FIELD_NUMBER: _ClassVar[int]
    OUTGOING_BITRATE_FIELD_NUMBER: _ClassVar[int]
    INCOMING_BITRATE_FIELD_NUMBER: _ClassVar[int]
    PROTOCOL_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    dest_uuid: str
    cumulative_rtt: float
    current_rtt: float
    outgoing_bitrate: float
    incoming_bitrate: float
    protocol: str
    type: Stats.ICEType

    def __init__(
        self,
        dest_uuid: _Optional[str] = ...,
        cumulative_rtt: _Optional[float] = ...,
        current_rtt: _Optional[float] = ...,
        outgoing_bitrate: _Optional[float] = ...,
        incoming_bitrate: _Optional[float] = ...,
        protocol: _Optional[str] = ...,
        type: _Optional[_Union[Stats.ICEType, str]] = ...,
    ) -> None: ...

class Event(_message.Message):
    __slots__ = ("data", "media", "achievedState", "stats")
    DATA_FIELD_NUMBER: _ClassVar[int]
    MEDIA_FIELD_NUMBER: _ClassVar[int]
    ACHIEVEDSTATE_FIELD_NUMBER: _ClassVar[int]
    STATS_FIELD_NUMBER: _ClassVar[int]
    data: DataTransmission
    media: MediaChannel
    achievedState: State
    stats: Stats

    def __init__(
        self,
        data: _Optional[_Union[DataTransmission, _Mapping]] = ...,
        media: _Optional[_Union[MediaChannel, _Mapping]] = ...,
        achievedState: _Optional[_Union[State, _Mapping]] = ...,
        stats: _Optional[_Union[Stats, _Mapping]] = ...,
    ) -> None: ...

class WebrtcConfig(_message.Message):
    __slots__ = ("ice_servers", "credentials")

    class IceServer(_message.Message):
        __slots__ = ("urls", "username", "credential", "credentialType")
        URLS_FIELD_NUMBER: _ClassVar[int]
        USERNAME_FIELD_NUMBER: _ClassVar[int]
        CREDENTIAL_FIELD_NUMBER: _ClassVar[int]
        CREDENTIALTYPE_FIELD_NUMBER: _ClassVar[int]
        urls: _containers.RepeatedScalarFieldContainer[str]
        username: str
        credential: str
        credentialType: str

        def __init__(
            self,
            urls: _Optional[_Iterable[str]] = ...,
            username: _Optional[str] = ...,
            credential: _Optional[str] = ...,
            credentialType: _Optional[str] = ...,
        ) -> None: ...

    class auth(_message.Message):
        __slots__ = ("cloudflare_auth", "onion_service_v3_auth")

        class CloudflareZeroTrust(_message.Message):
            __slots__ = ("client_id", "client_secret")
            CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
            CLIENT_SECRET_FIELD_NUMBER: _ClassVar[int]
            client_id: str
            client_secret: str

            def __init__(
                self, client_id: _Optional[str] = ..., client_secret: _Optional[str] = ...
            ) -> None: ...

        class TorOnionServiceV3(_message.Message):
            __slots__ = ()
            def __init__(self) -> None: ...
        CLOUDFLARE_AUTH_FIELD_NUMBER: _ClassVar[int]
        ONION_SERVICE_V3_AUTH_FIELD_NUMBER: _ClassVar[int]
        cloudflare_auth: WebrtcConfig.auth.CloudflareZeroTrust
        onion_service_v3_auth: WebrtcConfig.auth.TorOnionServiceV3

        def __init__(
            self,
            cloudflare_auth: _Optional[
                _Union[WebrtcConfig.auth.CloudflareZeroTrust, _Mapping]
            ] = ...,
            onion_service_v3_auth: _Optional[
                _Union[WebrtcConfig.auth.TorOnionServiceV3, _Mapping]
            ] = ...,
        ) -> None: ...

    class CredentialsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: WebrtcConfig.auth

        def __init__(
            self,
            key: _Optional[str] = ...,
            value: _Optional[_Union[WebrtcConfig.auth, _Mapping]] = ...,
        ) -> None: ...
    ICE_SERVERS_FIELD_NUMBER: _ClassVar[int]
    CREDENTIALS_FIELD_NUMBER: _ClassVar[int]
    ice_servers: _containers.RepeatedCompositeFieldContainer[WebrtcConfig.IceServer]
    credentials: _containers.MessageMap[str, WebrtcConfig.auth]

    def __init__(
        self,
        ice_servers: _Optional[_Iterable[_Union[WebrtcConfig.IceServer, _Mapping]]] = ...,
        credentials: _Optional[_Mapping[str, WebrtcConfig.auth]] = ...,
    ) -> None: ...

class HttpServer(_message.Message):
    __slots__ = ("address", "cloudflare_auth", "onion_service_v3_auth")

    class CloudflareTunnel(_message.Message):
        __slots__ = ("team_domain", "team_aud")
        TEAM_DOMAIN_FIELD_NUMBER: _ClassVar[int]
        TEAM_AUD_FIELD_NUMBER: _ClassVar[int]
        team_domain: str
        team_aud: str

        def __init__(
            self, team_domain: _Optional[str] = ..., team_aud: _Optional[str] = ...
        ) -> None: ...

    class TorOnionServiceV3(_message.Message):
        __slots__ = ("hs_ed25519_secret_key", "anonymous")
        HS_ED25519_SECRET_KEY_FIELD_NUMBER: _ClassVar[int]
        ANONYMOUS_FIELD_NUMBER: _ClassVar[int]
        hs_ed25519_secret_key: bytes
        anonymous: bool

        def __init__(
            self, hs_ed25519_secret_key: _Optional[bytes] = ..., anonymous: bool = ...
        ) -> None: ...
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    CLOUDFLARE_AUTH_FIELD_NUMBER: _ClassVar[int]
    ONION_SERVICE_V3_AUTH_FIELD_NUMBER: _ClassVar[int]
    address: str
    cloudflare_auth: HttpServer.CloudflareTunnel
    onion_service_v3_auth: HttpServer.TorOnionServiceV3

    def __init__(
        self,
        address: _Optional[str] = ...,
        cloudflare_auth: _Optional[_Union[HttpServer.CloudflareTunnel, _Mapping]] = ...,
        onion_service_v3_auth: _Optional[_Union[HttpServer.TorOnionServiceV3, _Mapping]] = ...,
    ) -> None: ...

class State(_message.Message):
    __slots__ = ("data", "media", "wantedTracks", "config", "reconnectAttempts", "httpServerConfig")
    DATA_FIELD_NUMBER: _ClassVar[int]
    MEDIA_FIELD_NUMBER: _ClassVar[int]
    WANTEDTRACKS_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    RECONNECTATTEMPTS_FIELD_NUMBER: _ClassVar[int]
    HTTPSERVERCONFIG_FIELD_NUMBER: _ClassVar[int]
    data: _containers.RepeatedCompositeFieldContainer[DataChannel]
    media: _containers.RepeatedCompositeFieldContainer[MediaChannel]
    wantedTracks: _containers.RepeatedCompositeFieldContainer[MediaChannel]
    config: WebrtcConfig
    reconnectAttempts: int
    httpServerConfig: HttpServer

    def __init__(
        self,
        data: _Optional[_Iterable[_Union[DataChannel, _Mapping]]] = ...,
        media: _Optional[_Iterable[_Union[MediaChannel, _Mapping]]] = ...,
        wantedTracks: _Optional[_Iterable[_Union[MediaChannel, _Mapping]]] = ...,
        config: _Optional[_Union[WebrtcConfig, _Mapping]] = ...,
        reconnectAttempts: _Optional[int] = ...,
        httpServerConfig: _Optional[_Union[HttpServer, _Mapping]] = ...,
    ) -> None: ...

class Mutation(_message.Message):
    __slots__ = ("data", "setState")
    DATA_FIELD_NUMBER: _ClassVar[int]
    SETSTATE_FIELD_NUMBER: _ClassVar[int]
    data: DataTransmission
    setState: State

    def __init__(
        self,
        data: _Optional[_Union[DataTransmission, _Mapping]] = ...,
        setState: _Optional[_Union[State, _Mapping]] = ...,
    ) -> None: ...
