/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AudioDevice } from '../models/AudioDevice';
import type { AudioDeviceOptions } from '../models/AudioDeviceOptions';
import type { VideoDevice } from '../models/VideoDevice';
import type { WebrtcOffer_Input } from '../models/WebrtcOffer_Input';
import type { WebrtcOffer_Output } from '../models/WebrtcOffer_Output';

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
     * Webrtc Offer
     * @param requestBody
     * @returns WebrtcOffer_Output Successful Response
     * @throws ApiError
     */
    public webrtcOffer(
        requestBody: WebrtcOffer_Input,
    ): CancelablePromise<WebrtcOffer_Output> {
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
