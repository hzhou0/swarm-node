/* eslint-disable */
/**
 * This file was automatically generated by json-schema-to-typescript.
 * DO NOT MODIFY IT BY HAND. Instead, modify the source JSONSchema file,
 * and run json-schema-to-typescript to regenerate this file.
 */

export interface DeviceState {
  meta: {
    version: "2022.5.14";
    [k: string]: unknown;
  };
  controlResponse?: {
    /**
     * Generated random id representing the current session
     */
    sessionId: string;
    /**
     * Version number of control docs issued in the current session. Starts at 0
     */
    v: number;
  };
  webrtc?: {
    sdp: string;
  };
  mode: "SAFE" | "MANUAL" | "AUTO";
  /**
   * Device epoch utc time (seconds)
   */
  utcEpoch: number;
  /**
   * GPS latitude
   */
  latitude?: number;
  /**
   * GPS longitude
   */
  longitude?: number;
  /**
   * Velocity (x,y,z) of the device in m/s. +y is defined as front of the robot.
   *
   * @minItems 3
   * @maxItems 3
   */
  velocity?: [number, number, number];
  /**
   * Angular velocity (x,y,z) of the device in deg/s. +y is defined as front of the robot.
   *
   * @minItems 3
   * @maxItems 3
   */
  angularVelocity?: [number, number, number];
  /**
   * 3 axis acceleration (x,y,z) acceleration of the device
   *
   * @minItems 3
   * @maxItems 3
   */
  acceleration?: [number, number, number];
  /**
   * Battery percentage
   */
  battery?: number;
  /**
   * List of ultrasonic readings (meters) counterclockwise from front of vehicle.
   *
   * @minItems 4
   * @maxItems 4
   */
  ultrasonics?: [number, number, number, number];
}