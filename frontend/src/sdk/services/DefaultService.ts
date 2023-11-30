/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { models_AudioDevice } from '../models/models_AudioDevice';
import type { models_AudioDeviceOptions } from '../models/models_AudioDeviceOptions';
import type { models_VideoDevice } from '../models/models_VideoDevice';
import type { models_WebrtcOffer } from '../models/models_WebrtcOffer';

import type { CancelablePromise } from '../core/CancelablePromise';
import type { BaseHttpRequest } from '../core/BaseHttpRequest';

export class DefaultService {

    constructor(public readonly httpRequest: BaseHttpRequest) {}

    /**
     * ListAudioDevices
     * @param type
     * @param includeProperties
     * @returns models_AudioDevice Request fulfilled, document follows
     * @throws ApiError
     */
    public listAudioDevices(
        type?: 'sink' | 'source',
        includeProperties?: boolean,
    ): CancelablePromise<Array<models_AudioDevice>> {
        return this.httpRequest.request({
            method: 'GET',
            url: '/api/devices/audio',
            query: {
                'type': type,
                'include_properties': includeProperties,
            },
            errors: {
                400: `Bad request syntax or unsupported method`,
            },
        });
    }

    /**
     * PutAudioDevice
     * @param requestBody
     * @returns any Request fulfilled, document follows
     * @throws ApiError
     */
    public putAudioDevice(
        requestBody: models_AudioDeviceOptions,
    ): CancelablePromise<any> {
        return this.httpRequest.request({
            method: 'PUT',
            url: '/api/devices/audio',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                400: `Bad request syntax or unsupported method`,
            },
        });
    }

    /**
     * ListVideoDevices
     * @returns models_VideoDevice Request fulfilled, document follows
     * @throws ApiError
     */
    public listVideoDevices(): CancelablePromise<Array<models_VideoDevice>> {
        return this.httpRequest.request({
            method: 'GET',
            url: '/api/devices/video',
        });
    }

    /**
     * WebrtcOffer
     * @param requestBody
     * @returns models_WebrtcOffer Document created, URL follows
     * @throws ApiError
     */
    public webrtcOffer(
        requestBody: models_WebrtcOffer,
    ): CancelablePromise<models_WebrtcOffer> {
        return this.httpRequest.request({
            method: 'POST',
            url: '/api/webrtc',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                400: `Bad request syntax or unsupported method`,
            },
        });
    }

}
