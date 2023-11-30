/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */

import type { models_AudioTrack } from './models_AudioTrack';
import type { models_VideoTrack } from './models_VideoTrack';

export type models_Tracks = {
    client_video?: boolean;
    client_audio?: boolean;
    machine_video?: (null | models_VideoTrack);
    machine_audio?: (null | models_AudioTrack);
};

