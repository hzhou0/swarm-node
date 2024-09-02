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
export type IceServer = {
    urls: string;
    username?: null | string;
    credential?: null | string;
};
export type WebrtcInfo = {
    ice_servers: IceServer[];
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
export type SysPerf = {
    cpu_freq_mhz: number;
    cpu_percent: number;
    cpu_load_avg_per_core_percent: number;
    disk_total_bytes: number;
    disk_free_bytes: number;
    mem_total_bytes: number;
    mem_available_bytes: number;
    swap_bytes: number;
};
export type ProcessPerf = {
    cpu_num: number;
    cpu_percent: number;
    mem_uss_percent: number;
    mem_uss_bytes: number;
    mem_pss_bytes: number;
    swap_bytes: number;
    create_time_epoch: number;
    niceness: number;
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
export function putAudioDevice(audioDeviceOptions: AudioDeviceOptions, opts?: Oazapfts.RequestOpts) {
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
        body: audioDeviceOptions
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
 * WebrtcInfo
 */
export function webrtcInfo(opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: WebrtcInfo;
    }>("/api/webrtc", {
        ...opts
    }));
}
/**
 * WebrtcOffer
 */
export function webrtcOffer(webrtcOffer: WebrtcOffer, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
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
        method: "PUT",
        body: webrtcOffer
    })));
}
/**
 * GetSystemPerformance
 */
export function getSystemPerformance(opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: SysPerf;
    }>("/api/perf/system", {
        ...opts
    }));
}
/**
 * ListProcessPerformance
 */
export function listProcessPerformance(opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: {
            [key: string]: ProcessPerf;
        };
    }>("/api/perf/processes", {
        ...opts
    }));
}
