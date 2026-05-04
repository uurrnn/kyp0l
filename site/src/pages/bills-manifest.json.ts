import type { APIRoute } from "astro";
import { getBills, billStatusTone } from "~/lib/data";
import type { BillManifestItem } from "~/lib/bills-manifest";

export const prerender = true;

export const GET: APIRoute = () => {
  const bills = getBills();
  const manifest: BillManifestItem[] = bills.map((b) => ({
    id: b.id,
    identifier: b.identifier,
    title: b.title,
    subjects: b.subjects,
    statusTone: billStatusTone(b),
    statusText: b.current_status,
    lastActionDate: b.last_action_date,
    bodyIds: b.body_ids,
    session: b.session,
  }));
  return new Response(JSON.stringify(manifest), {
    headers: { "content-type": "application/json" },
  });
};
