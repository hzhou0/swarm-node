import { ref, Ref } from "vue";
import { Client } from "@/sdk";

const baseClient = new Client({
  BASE: import.meta.env.DEV ? "http://localhost:8080" : window.location.origin,
  HEADERS: {
    "Content-Type": "application/json",
  },
});
export const client = baseClient.default;

export class Fetcher<T extends { [k: string]: () => Promise<any> }> {
  private _data: Ref<{ [P in keyof T]?: Awaited<ReturnType<T[P]>> }> = ref({});
  private handler?: number;

  constructor(
    public readonly dataSources: T,
    private timeout?: number,
  ) {
    this.fetch().then(() => {
      if (timeout != undefined) {
        this.periodicFetch(timeout);
      }
    });
  }

  get data() {
    return this._data.value;
  }

  get ref() {
    return this._data;
  }

  private fetch = async () => {
    const dataKeys: (keyof T)[] = Object.keys(this.dataSources);
    await Promise.allSettled(
      dataKeys.map(async (k) => {
        this._data.value[k] = await this.dataSources[k]().catch(() => undefined);
      }),
    );
  };

  periodicFetch = (timeout: number) => {
    this.timeout = timeout;
    this.handler = setInterval(this.fetch, this.timeout);
  };

  stopPeriodicFetch = () => {
    clearInterval(this.handler);
  };

  fetchNow = async () => {
    this.stopPeriodicFetch();
    await this.fetch();
    if (this.timeout) {
      this.periodicFetch(this.timeout);
    }
  };
}

export function dedupe<T>(arr: T[]) {
  return [...new Set(arr)];
}
