/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */

export type AudioDevice = {
    name: string;
    default: boolean;
    volume: number;
    mute: boolean;
    description: string;
    driver: string;
    form_factor: 'car' | 'computer' | 'hands-free' | 'handset' | 'headphone' | 'headset' | 'hifi' | 'internal' | 'microphone' | 'portable' | 'speaker' | 'tv' | 'webcam';
    index: number;
    is_monitor: boolean;
    state: 'idle' | 'invalid' | 'running' | 'suspended';
    type: 'sink' | 'source';
    properties?: (Record<string, any> | null);
};

