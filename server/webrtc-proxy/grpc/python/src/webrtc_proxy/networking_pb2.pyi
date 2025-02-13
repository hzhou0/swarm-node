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
    __slots__ = ("src_uuid", "dest_uuid", "track", "close")
    SRC_UUID_FIELD_NUMBER: _ClassVar[int]
    DEST_UUID_FIELD_NUMBER: _ClassVar[int]
    TRACK_FIELD_NUMBER: _ClassVar[int]
    CLOSE_FIELD_NUMBER: _ClassVar[int]
    src_uuid: str
    dest_uuid: str
    track: NamedTrack
    close: bool
    def __init__(
        self,
        src_uuid: _Optional[str] = ...,
        dest_uuid: _Optional[str] = ...,
        track: _Optional[_Union[NamedTrack, _Mapping]] = ...,
        close: bool = ...,
    ) -> None: ...

class MediaSocketDirs(_message.Message):
    __slots__ = ("serverDir", "clientDir")
    SERVERDIR_FIELD_NUMBER: _ClassVar[int]
    CLIENTDIR_FIELD_NUMBER: _ClassVar[int]
    serverDir: str
    clientDir: str
    def __init__(
        self, serverDir: _Optional[str] = ..., clientDir: _Optional[str] = ...
    ) -> None: ...

class Event(_message.Message):
    __slots__ = ("data", "media", "achievedState", "mediaSocketDirs")
    DATA_FIELD_NUMBER: _ClassVar[int]
    MEDIA_FIELD_NUMBER: _ClassVar[int]
    ACHIEVEDSTATE_FIELD_NUMBER: _ClassVar[int]
    MEDIASOCKETDIRS_FIELD_NUMBER: _ClassVar[int]
    data: DataTransmission
    media: MediaChannel
    achievedState: State
    mediaSocketDirs: MediaSocketDirs
    def __init__(
        self,
        data: _Optional[_Union[DataTransmission, _Mapping]] = ...,
        media: _Optional[_Union[MediaChannel, _Mapping]] = ...,
        achievedState: _Optional[_Union[State, _Mapping]] = ...,
        mediaSocketDirs: _Optional[_Union[MediaSocketDirs, _Mapping]] = ...,
    ) -> None: ...

class WebrtcConfig(_message.Message):
    __slots__ = ("ice_servers", "cloudflare")

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

    class CloudflareZeroTrust(_message.Message):
        __slots__ = ("client_id", "client_secret")
        CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
        CLIENT_SECRET_FIELD_NUMBER: _ClassVar[int]
        client_id: str
        client_secret: str

        def __init__(
            self, client_id: _Optional[str] = ..., client_secret: _Optional[str] = ...
        ) -> None: ...
    ICE_SERVERS_FIELD_NUMBER: _ClassVar[int]
    CLOUDFLARE_FIELD_NUMBER: _ClassVar[int]
    ice_servers: _containers.RepeatedCompositeFieldContainer[WebrtcConfig.IceServer]
    cloudflare: WebrtcConfig.CloudflareZeroTrust

    def __init__(
        self,
        ice_servers: _Optional[_Iterable[_Union[WebrtcConfig.IceServer, _Mapping]]] = ...,
        cloudflare: _Optional[_Union[WebrtcConfig.CloudflareZeroTrust, _Mapping]] = ...,
    ) -> None: ...

class HttpServer(_message.Message):
    __slots__ = ("address", "none", "cloudflare")

    class CloudflareTunnel(_message.Message):
        __slots__ = ("team_domain", "team_aud")
        TEAM_DOMAIN_FIELD_NUMBER: _ClassVar[int]
        TEAM_AUD_FIELD_NUMBER: _ClassVar[int]
        team_domain: str
        team_aud: str

        def __init__(
            self, team_domain: _Optional[str] = ..., team_aud: _Optional[str] = ...
        ) -> None: ...

    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    NONE_FIELD_NUMBER: _ClassVar[int]
    CLOUDFLARE_FIELD_NUMBER: _ClassVar[int]
    address: str
    none: bool
    cloudflare: HttpServer.CloudflareTunnel

    def __init__(
        self,
        address: _Optional[str] = ...,
        none: bool = ...,
        cloudflare: _Optional[_Union[HttpServer.CloudflareTunnel, _Mapping]] = ...,
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
    wantedTracks: _containers.RepeatedCompositeFieldContainer[NamedTrack]
    config: WebrtcConfig
    reconnectAttempts: int
    httpServerConfig: HttpServer

    def __init__(
        self,
        data: _Optional[_Iterable[_Union[DataChannel, _Mapping]]] = ...,
        media: _Optional[_Iterable[_Union[MediaChannel, _Mapping]]] = ...,
        wantedTracks: _Optional[_Iterable[_Union[NamedTrack, _Mapping]]] = ...,
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
