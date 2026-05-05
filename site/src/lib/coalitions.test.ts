import { describe, it, expect } from "vitest";

// Lightweight smoke check — coalitions.ts is heavy on real-data accessors,
// so the meaningful test is build verification + render. Unit-test the
// pure shape: that the module exports the public API without throwing on
// the empty case (no bills with populated person_ids).
import { getCoalitionData, getCoalitionPartners } from "./coalitions";

describe("coalitions", () => {
  it("returns a usable shape even when person_ids are unpopulated", () => {
    const d = getCoalitionData();
    expect(Array.isArray(d.pairs)).toBe(true);
    expect(Array.isArray(d.connected)).toBe(true);
    expect(typeof d.partyMix.withinParty).toBe("number");
    expect(typeof d.partyMix.crossParty).toBe("number");
    expect(d.partyMix.byChamber.lower).toBeDefined();
    expect(d.partyMix.byChamber.upper).toBeDefined();
  });

  it("returns an empty list for an unknown person slug", () => {
    expect(getCoalitionPartners("ky-not-a-real-person")).toEqual([]);
  });
});
