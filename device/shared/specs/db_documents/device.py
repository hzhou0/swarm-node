from typing import Literal, TypedDict, Union, List
from typing_extensions import Required


class DeviceState(TypedDict, total=False):
    """ Device State. """

    meta: Required["_DeviceStateMeta"]
    """ Required property """

    controlResponse: "_DeviceStateControlresponse"
    webrtc: "_DeviceStateWebrtc"
    mode: Required["_DeviceStateMode"]
    """ Required property """

    utcEpoch: Required[Union[int, float]]
    """
    Device epoch utc time (seconds)

    minimum: 0

    Required property
    """

    latitude: Union[int, float]
    """
    GPS latitude

    minimum: -90
    maximum: 90
    """

    longitude: Union[int, float]
    """
    GPS longitude

    minimum: -90
    maximum: 90
    """

    velocity: List[Union[int, float]]
    """
    Velocity (x,y,z) of the device in m/s. +y is defined as front of the robot.

    minItems: 3
    maxItems: 3
    """

    angularVelocity: List[Union[int, float]]
    """
    Angular velocity (x,y,z) of the device in deg/s. +y is defined as front of the robot.

    minItems: 3
    maxItems: 3
    """

    acceleration: List[Union[int, float]]
    """
    3 axis acceleration (x,y,z) acceleration of the device

    minItems: 3
    maxItems: 3
    """

    battery: Union[int, float]
    """
    Battery percentage

    minimum: 0
    maximum: 100
    """

    ultrasonics: List["_DeviceStateUltrasonicsItem"]
    """
    List of ultrasonic readings (meters) counterclockwise from front of vehicle.

    minItems: 4
    maxItems: 4
    """



class _DeviceStateControlresponse(TypedDict, total=False):
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



class _DeviceStateMeta(TypedDict, total=False):
    version: Required[Literal["2022.5.14"]]
    """ Required property """



_DeviceStateMode = Union[Literal["SAFE"], Literal["MANUAL"], Literal["AUTO"]]
_DEVICESTATEMODE_SAFE: Literal["SAFE"] = "SAFE"
"""The values for the '_DeviceStateMode' enum"""
_DEVICESTATEMODE_MANUAL: Literal["MANUAL"] = "MANUAL"
"""The values for the '_DeviceStateMode' enum"""
_DEVICESTATEMODE_AUTO: Literal["AUTO"] = "AUTO"
"""The values for the '_DeviceStateMode' enum"""



_DeviceStateUltrasonicsItem = Union[int, float]
""" minimum: 0 """



class _DeviceStateWebrtc(TypedDict, total=False):
    sdp: Required[str]
    """ Required property """

