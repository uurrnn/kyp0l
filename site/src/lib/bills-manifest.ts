import type { StatusTone } from "./data";

export interface BillManifestItem {
  id: string;
  identifier: string;
  title: string;
  subjects: string[];
  statusTone: StatusTone;
  statusText: string;
  lastActionDate: string;
  bodyIds: string[];
  session: string;
}

export type BillManifest = BillManifestItem[];
