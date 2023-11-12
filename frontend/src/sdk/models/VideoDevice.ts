/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */

import type { VideoSize } from './VideoSize';

export type VideoDevice = {
    name: string;
    index: number;
    closed: boolean;
    description: string;
    capabilities: Array<string>;
    video_sizes: Array<VideoSize>;
};

