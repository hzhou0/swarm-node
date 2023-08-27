import PouchDB from "pouchdb";
import webrtc from "../../shared/constants/webrtc.json";
import { ControlState } from "../../shared/specs/db_documents/control";
import { DeviceState } from "../../shared/specs/db_documents/device";
import _ from "lodash";

type ControlStateDB = ControlState & PouchDB.Core.GetMeta;
type DeviceStateDB = DeviceState & PouchDB.Core.GetMeta;

function toControlState(
  state: Omit<ControlState, "utcEpoch" | "meta">
): ControlState {
  return {
    utcEpoch: Date.now(),
    meta: { version: "2022.5.14" },
    ...state,
  };
}

export default class Connection {
  static LOCK_DURATION_MS = 10 * 1000;
  private fetchControl = false;
  private fetchDevice = false;

  private constructor(
    private db: PouchDB.Database,
    private sessionId: string,
    private v: number,
    private _control: ControlStateDB,
    private _device: DeviceStateDB,
    public controlMutex: boolean
  ) {
    void this.syncControl();
  }

  static mutexValid(utcEpoch: number) {
    return Math.abs(utcEpoch - Date.now()) <= Connection.LOCK_DURATION_MS;
  }

  async setControl(
    c: Omit<ControlState, "utcEpoch" | "meta" | "v" | "sessionId">
  ) {
    this._control = await this.control();
    if (!Connection.mutexValid(this._control.utcEpoch)) {
      this.controlMutex = true;
    }
    if (!this.controlMutex) {
      throw new Error("Does not posses mutex of control document.");
    }

    this.v++;
    await this.db.put({
      _id: webrtc.CONTROL_DOC,
      _rev: this._control._rev,
      ...toControlState({ v: this.v, sessionId: this.sessionId, ...c }),
    });
    this._control = await this.control();
  }

  private async syncControl() {
    this._control = await this.db.get(webrtc.CONTROL_DOC);
    if (
      this._control.sessionId == this.sessionId ||
      !Connection.mutexValid(this._control.utcEpoch)
    ) {
      await this.setControl({}); //Refresh lease on mutex utcEpoch
    } else {
      this.controlMutex = false;
    }
    setTimeout(this.syncControl, Connection.LOCK_DURATION_MS / 2);
  }

  async control() {
    if (!this.controlMutex && this.fetchControl) {
      this._control = await this.db.get(webrtc.CONTROL_DOC);
      this.fetchControl = false;
      setTimeout(() => (this.fetchControl = true), 100);
    }
    return this._control;
  }

  async device() {
    if (this.fetchDevice) {
      this._device = await this.db.get(webrtc.DEVICE_DOC);
      this.fetchDevice = false;
      setTimeout(() => (this.fetchDevice = true), 100);
    }
    return this._device;
  }

  static async init(name: string, jwt: string) {
    const db = new PouchDB(`${webrtc.DB_URL}/d_${name}`, {
      skip_setup: true,
      fetch: (url, opts) => {
        (<Headers>opts).set("Authorization", `Bearer ${jwt}`); // Use jwt auth
        return PouchDB.fetch(url, opts);
      },
    });

    const sessionId = self.crypto.randomUUID();
    const v = 0;
    let controlMutex = false;
    // todo: implement database schema validation
    let _control: ControlStateDB;
    try {
      _control = await db.get(webrtc.CONTROL_DOC);
      if (!Connection.mutexValid(_control.utcEpoch)) {
        await db.put({
          _id: webrtc.CONTROL_DOC,
          _rev: _control._rev,
          ...toControlState({ v, sessionId }),
        });
        controlMutex = true;
        _control = await db.get(webrtc.CONTROL_DOC);
      }
    } catch (e) {
      console.warn(e);
      await db.put({
        _id: webrtc.CONTROL_DOC,
        ...toControlState({ v, sessionId }),
      });
      _control = await db.get(webrtc.CONTROL_DOC);
      controlMutex = true;
    }

    let _device: DeviceStateDB;
    try {
      _device = await db.get(webrtc.DEVICE_DOC);
    } catch (e) {
      console.error("Device document not found. Is the device offline?");
      throw e;
    }
    return new Connection(db, sessionId, v, _control, _device, controlMutex);
  }
}
