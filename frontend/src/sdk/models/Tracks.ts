/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */

import type { AudioTrack } from './AudioTrack';
import type { VideoTrack } from './VideoTrack';

export type Tracks = {
    client_video?: boolean;
    client_audio?: boolean;
    machine_video?: (VideoTrack | null);
    machine_audio?: (AudioTrack | null);
};

