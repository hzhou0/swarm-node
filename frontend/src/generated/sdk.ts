/* eslint-disable */
/**
 * Shop Cart
 * 0.1.0
 * DO NOT MODIFY - This file has been generated using oazapfts.
 * See https://www.npmjs.com/package/oazapfts
 */
import * as Oazapfts from "oazapfts/lib/runtime";
import * as QS from "oazapfts/lib/runtime/query";
export const defaults: Oazapfts.RequestOpts = {
    baseUrl: "/",
};
const oazapfts = Oazapfts.runtime(defaults);
export const servers = {
    server1: "/"
};
export type AudioDevice = {
    name: string;
    "default": boolean;
    volume: number;
    mute: boolean;
    description: string;
    driver: string;
    index: number;
    is_monitor: boolean;
    state: "idle" | "invalid" | "running" | "suspended";
    "type": "sink" | "source";
    properties?: null | {
        [key: string]: any;
    };
    form_factor?: "car" | "computer" | "hands-free" | "handset" | "headphone" | "headset" | "hifi" | "internal" | "microphone" | "portable" | "speaker" | "tv" | "webcam" | "unknown" | null;
};
export type AudioDeviceOptions = {
    name: string;
    "default": boolean;
    volume: number;
    mute: boolean;
};
export type VideoSize = {
    height: number;
    width: number;
    fps: number[];
    format: string;
};
export type VideoDevice = {
    name: string;
    index: number;
    closed: boolean;
    description: string;
    capabilities: string[];
    video_sizes: VideoSize[];
};
export type VideoTrack = {
    name: string;
    height: number;
    width: number;
    fps: number;
    format: string;
};
export type AudioTrack = {
    name: string;
};
export type Tracks = {
    client_video?: boolean;
    client_audio?: boolean;
    machine_video?: null | VideoTrack;
    machine_audio?: null | AudioTrack;
};
export type WebrtcOffer = {
    sdp: string;
    "type": "answer" | "offer" | "pranswer" | "rollback";
    tracks: Tracks;
};
/**
 * ListAudioDevices
 */
export function listAudioDevices({ $type, includeProperties }: {
    $type?: "sink" | "source" | null;
    includeProperties?: boolean;
} = {}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: AudioDevice[];
    } | {
        status: 400;
        data: {
            status_code: number;
            detail: string;
            extra?: {
                [key: string]: any;
            };
        };
    }>(`/api/devices/audio${QS.query(QS.explode({
        "type": $type,
        include_properties: includeProperties
    }))}`, {
        ...opts
    }));
}
/**
 * PutAudioDevice
 */
export function putAudioDevice(modelsAudioDeviceOptions: AudioDeviceOptions, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
    } | {
        status: 400;
        data: {
            status_code: number;
            detail: string;
            extra?: {
                [key: string]: any;
            };
        };
    }>("/api/devices/audio", oazapfts.json({
        ...opts,
        method: "PUT",
        body: modelsAudioDeviceOptions
    })));
}
/**
 * ListVideoDevices
 */
export function listVideoDevices(opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: VideoDevice[];
    }>("/api/devices/video", {
        ...opts
    }));
}
/**
 * WebrtcOffer
 */
export function webrtcOffer(modelsWebrtcOffer: WebrtcOffer, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 201;
        data: WebrtcOffer;
    } | {
        status: 400;
        data: {
            status_code: number;
            detail: string;
            extra?: {
                [key: string]: any;
            };
        };
    }>("/api/webrtc", oazapfts.json({
        ...opts,
        method: "POST",
        body: modelsWebrtcOffer
    })));
}
