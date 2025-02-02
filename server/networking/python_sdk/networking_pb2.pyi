from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class NamedTrack(_message.Message):
    __slots__ = ("track_id", "stream_id", "mime_type")
    TRACK_ID_FIELD_NUMBER: _ClassVar[int]
    STREAM_ID_FIELD_NUMBER: _ClassVar[int]
    MIME_TYPE_FIELD_NUMBER: _ClassVar[int]
    track_id: str
    stream_id: str
    mime_type: str
    def __init__(self, track_id: _Optional[str] = ..., stream_id: _Optional[str] = ..., mime_type: _Optional[str] = ...) -> None: ...

class WebrtcOffer(_message.Message):
    __slots__ = ("src_uuid", "sdp", "type", "local_tracks", "local_tracks_set", "remote_tracks", "remote_tracks_set", "datachannel")
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
    def __init__(self, src_uuid: _Optional[str] = ..., sdp: _Optional[str] = ..., type: _Optional[str] = ..., local_tracks: _Optional[_Iterable[_Union[NamedTrack, _Mapping]]] = ..., local_tracks_set: bool = ..., remote_tracks: _Optional[_Iterable[_Union[NamedTrack, _Mapping]]] = ..., remote_tracks_set: bool = ..., datachannel: bool = ...) -> None: ...

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
    def __init__(self, channel: _Optional[_Union[DataChannel, _Mapping]] = ..., payload: _Optional[bytes] = ...) -> None: ...

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
    def __init__(self, src_uuid: _Optional[str] = ..., dest_uuid: _Optional[str] = ..., track: _Optional[_Union[NamedTrack, _Mapping]] = ..., close: bool = ...) -> None: ...

class Event(_message.Message):
    __slots__ = ("data", "media", "achievedState")
    DATA_FIELD_NUMBER: _ClassVar[int]
    MEDIA_FIELD_NUMBER: _ClassVar[int]
    ACHIEVEDSTATE_FIELD_NUMBER: _ClassVar[int]
    data: DataTransmission
    media: MediaChannel
    achievedState: State
    def __init__(self, data: _Optional[_Union[DataTransmission, _Mapping]] = ..., media: _Optional[_Union[MediaChannel, _Mapping]] = ..., achievedState: _Optional[_Union[State, _Mapping]] = ...) -> None: ...

class WebrtcConfig(_message.Message):
    __slots__ = ("ice_servers",)
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
        def __init__(self, urls: _Optional[_Iterable[str]] = ..., username: _Optional[str] = ..., credential: _Optional[str] = ..., credentialType: _Optional[str] = ...) -> None: ...
    ICE_SERVERS_FIELD_NUMBER: _ClassVar[int]
    ice_servers: _containers.RepeatedCompositeFieldContainer[WebrtcConfig.IceServer]
    def __init__(self, ice_servers: _Optional[_Iterable[_Union[WebrtcConfig.IceServer, _Mapping]]] = ...) -> None: ...

class State(_message.Message):
    __slots__ = ("data", "media", "wantedTracks", "config", "reconnectAttempts", "httpAddr")
    DATA_FIELD_NUMBER: _ClassVar[int]
    MEDIA_FIELD_NUMBER: _ClassVar[int]
    WANTEDTRACKS_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    RECONNECTATTEMPTS_FIELD_NUMBER: _ClassVar[int]
    HTTPADDR_FIELD_NUMBER: _ClassVar[int]
    data: _containers.RepeatedCompositeFieldContainer[DataChannel]
    media: _containers.RepeatedCompositeFieldContainer[MediaChannel]
    wantedTracks: _containers.RepeatedCompositeFieldContainer[NamedTrack]
    config: WebrtcConfig
    reconnectAttempts: int
    httpAddr: str
    def __init__(self, data: _Optional[_Iterable[_Union[DataChannel, _Mapping]]] = ..., media: _Optional[_Iterable[_Union[MediaChannel, _Mapping]]] = ..., wantedTracks: _Optional[_Iterable[_Union[NamedTrack, _Mapping]]] = ..., config: _Optional[_Union[WebrtcConfig, _Mapping]] = ..., reconnectAttempts: _Optional[int] = ..., httpAddr: _Optional[str] = ...) -> None: ...

class Mutation(_message.Message):
    __slots__ = ("data", "setState")
    DATA_FIELD_NUMBER: _ClassVar[int]
    SETSTATE_FIELD_NUMBER: _ClassVar[int]
    data: DataTransmission
    setState: State
    def __init__(self, data: _Optional[_Union[DataTransmission, _Mapping]] = ..., setState: _Optional[_Union[State, _Mapping]] = ...) -> None: ...
