/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AudioDevice } from '../models/AudioDevice';
import type { AudioDeviceOptions } from '../models/AudioDeviceOptions';
import type { AudioStream } from '../models/AudioStream';
import type { VideoDevice } from '../models/VideoDevice';
import type { VideoStream } from '../models/VideoStream';
import type { webrtcInfo } from '../models/webrtcInfo';
import type { webrtcOffer } from '../models/webrtcOffer';

import type { CancelablePromise } from '../core/CancelablePromise';
import type { BaseHttpRequest } from '../core/BaseHttpRequest';

export class DefaultService {

    constructor(public readonly httpRequest: BaseHttpRequest) {}

    /**
     * List Audio Devices
     * @param type
     * @param includeProperties
     * @returns AudioDevice Successful Response
     * @throws ApiError
     */
    public listAudioDevices(
        type?: ('sink' | 'source' | null),
        includeProperties: boolean = false,
    ): CancelablePromise<Array<AudioDevice>> {
        return this.httpRequest.request({
            method: 'GET',
            url: '/api/devices/audio',
            query: {
                'type': type,
                'include_properties': includeProperties,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }

    /**
     * Put Audio Device
     * @param requestBody
     * @returns any Successful Response
     * @throws ApiError
     */
    public putAudioDevice(
        requestBody: AudioDeviceOptions,
    ): CancelablePromise<any> {
        return this.httpRequest.request({
            method: 'PUT',
            url: '/api/devices/audio',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }

    /**
     * List Video Devices
     * @returns VideoDevice Successful Response
     * @throws ApiError
     */
    public listVideoDevices(): CancelablePromise<Array<VideoDevice>> {
        return this.httpRequest.request({
            method: 'GET',
            url: '/api/devices/video',
        });
    }

    /**
     * Video Stream Info
     * @returns any Successful Response
     * @throws ApiError
     */
    public videoStreamInfo(): CancelablePromise<(VideoStream | null)> {
        return this.httpRequest.request({
            method: 'GET',
            url: '/api/stream/video',
        });
    }

    /**
     * Start Video Stream
     * @param requestBody
     * @returns any Successful Response
     * @throws ApiError
     */
    public startVideoStream(
        requestBody: VideoStream,
    ): CancelablePromise<any> {
        return this.httpRequest.request({
            method: 'PUT',
            url: '/api/stream/video',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }

    /**
     * Stop Video Stream
     * @returns any Successful Response
     * @throws ApiError
     */
    public stopVideoStream(): CancelablePromise<any> {
        return this.httpRequest.request({
            method: 'DELETE',
            url: '/api/stream/video',
        });
    }

    /**
     * Audio Stream Info
     * @returns any Successful Response
     * @throws ApiError
     */
    public audioStreamInfo(): CancelablePromise<(AudioStream | null)> {
        return this.httpRequest.request({
            method: 'GET',
            url: '/api/stream/audio',
        });
    }

    /**
     * Start Audio Stream
     * @param requestBody
     * @returns any Successful Response
     * @throws ApiError
     */
    public startAudioStream(
        requestBody: AudioStream,
    ): CancelablePromise<any> {
        return this.httpRequest.request({
            method: 'PUT',
            url: '/api/stream/audio',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }

    /**
     * Stop Audio Stream
     * @returns any Successful Response
     * @throws ApiError
     */
    public stopAudioStream(): CancelablePromise<any> {
        return this.httpRequest.request({
            method: 'DELETE',
            url: '/api/stream/audio',
        });
    }

    /**
     * Webrtc Info
     * @returns webrtcInfo Successful Response
     * @throws ApiError
     */
    public webrtcInfo(): CancelablePromise<webrtcInfo> {
        return this.httpRequest.request({
            method: 'GET',
            url: '/api/webrtc',
        });
    }

    /**
     * Webrtc Offer
     * @param requestBody
     * @returns webrtcOffer Successful Response
     * @throws ApiError
     */
    public webrtcOffer(
        requestBody: webrtcOffer,
    ): CancelablePromise<webrtcOffer> {
        return this.httpRequest.request({
            method: 'POST',
            url: '/api/webrtc',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }

}
