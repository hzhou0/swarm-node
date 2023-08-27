from typing import TypedDict, Literal, Union
from typing_extensions import Required


class ControlState(TypedDict, total=False):
    """ Control State. """

    meta: Required["_ControlStateMeta"]
    """ Required property """

    sessionId: Required[str]
    """
    Generated random id representing the current session

    Required property
    """

    v: Required[int]
    """
    Version number of control docs issued in the current session. Starts at 0

    minimum: 0

    Required property
    """

    utcEpoch: Required[int]
    """
    Command issue epoch utc time (ms)

    minimum: 0

    Required property
    """

    webrtc: "_ControlStateWebrtc"
    mode: "_ControlStateMode"


class _ControlStateMeta(TypedDict, total=False):
    version: Required[Literal["2022.5.14"]]
    """ Required property """



_ControlStateMode = Union[Literal["SAFE"], Literal["MANUAL"], Literal["AUTO"]]
_CONTROLSTATEMODE_SAFE: Literal["SAFE"] = "SAFE"
"""The values for the '_ControlStateMode' enum"""
_CONTROLSTATEMODE_MANUAL: Literal["MANUAL"] = "MANUAL"
"""The values for the '_ControlStateMode' enum"""
_CONTROLSTATEMODE_AUTO: Literal["AUTO"] = "AUTO"
"""The values for the '_ControlStateMode' enum"""



class _ControlStateWebrtc(TypedDict, total=False):
    sdp: Required[str]
    """ Required property """

