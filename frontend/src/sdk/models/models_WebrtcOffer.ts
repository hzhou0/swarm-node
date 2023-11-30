/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */

import type { models_Tracks } from './models_Tracks';

export type models_WebrtcOffer = {
    sdp: string;
    type: 'answer' | 'offer' | 'pranswer' | 'rollback';
    tracks: models_Tracks;
};

