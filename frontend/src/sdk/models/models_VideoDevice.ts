/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */

import type { models_VideoSize } from './models_VideoSize';

export type models_VideoDevice = {
    name: string;
    index: number;
    closed: boolean;
    description: string;
    capabilities: Array<string>;
    video_sizes: Array<models_VideoSize>;
};

