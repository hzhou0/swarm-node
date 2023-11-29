/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */

import type { Tracks } from './Tracks';

export type WebrtcOffer_Output = {
    sdp: string;
    type: 'answer' | 'offer' | 'pranswer' | 'rollback';
    tracks: Tracks;
};

