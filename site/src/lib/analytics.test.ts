import { describe, it, expect } from "vitest";
import {
  computeStatsFromFixture,
  type FixtureBill,
  type FixturePerson,
  type FixtureMemberVote,
} from "./analytics";

const ALICE: FixturePerson = { id: "ky-alice", chamber: "lower", party: "Democratic" };
const BOB: FixturePerson = { id: "ky-bob", chamber: "lower", party: "Republican" };

const ALICE_OCD = "ocd-person/alice";
const BOB_OCD = "ocd-person/bob";

const fixturePeopleIndex = new Map<string, string>([
  [ALICE_OCD, ALICE.id],
  [BOB_OCD, BOB.id],
]);

const bill1: FixtureBill = {
  id: "b1",
  subjects: ["Education"],
  chamber_progress: { lower: "passed", upper: null, governor: null },
  actions: [],
  current_status: "Passed House",
  sponsors: [
    { person_id: ALICE_OCD, party: "Democratic", primary: true },
    { person_id: BOB_OCD, party: "Republican", primary: false },
  ],
  votes: [
    {
      chamber: "lower",
      member_votes: [
        { person_id: ALICE_OCD, option: "yes" },
        { person_id: BOB_OCD, option: "no" },
      ],
    },
  ],
};

const bill2: FixtureBill = {
  id: "b2",
  subjects: ["Health"],
  chamber_progress: { lower: null, upper: null, governor: null },
  actions: [],
  current_status: "Introduced",
  sponsors: [
    { person_id: BOB_OCD, party: "Republican", primary: true },
    { person_id: ALICE_OCD, party: "Democratic", primary: false },
  ],
  votes: [],
};

describe("counts", () => {
  it("counts primary, co-sponsored, and votes per person", () => {
    const stats = computeStatsFromFixture([bill1, bill2], [ALICE, BOB], fixturePeopleIndex);
    const a = stats.get("ky-alice")!;
    const b = stats.get("ky-bob")!;

    expect(a.billsPrimarySponsored).toBe(1);
    expect(a.billsCoSponsored).toBe(1);
    expect(a.votesCast).toBe(1);
    expect(a.votesParticipated).toBe(1);

    expect(b.billsPrimarySponsored).toBe(1);
    expect(b.billsCoSponsored).toBe(1);
    expect(b.votesCast).toBe(1);
    expect(b.votesParticipated).toBe(1);
  });

  it("excludes member_votes with null person_id from per-person tallies", () => {
    const billWithNull: FixtureBill = {
      ...bill1,
      votes: [
        {
          chamber: "lower",
          member_votes: [
            { person_id: null, option: "yes" },
            { person_id: ALICE_OCD, option: "yes" },
          ] as FixtureMemberVote[],
        },
      ],
    };
    const stats = computeStatsFromFixture([billWithNull], [ALICE, BOB], fixturePeopleIndex);
    expect(stats.get("ky-alice")!.votesCast).toBe(1);
    expect(stats.get("ky-bob")!.votesCast).toBe(0);
  });
});

describe("partyLoyaltyRate", () => {
  const FILLER: FixturePerson[] = Array.from({ length: 30 }, (_, i) => ({
    id: `ky-d-${i}`,
    chamber: "lower",
    party: "Democratic",
  }));
  const FILLER_INDEX = new Map<string, string>(FILLER.map((p) => [`ocd-person/d-${p.id.slice(5)}`, p.id]));

  function dvote(option: string, startIdx: number, n: number): FixtureMemberVote[] {
    return Array.from({ length: n }, (_, i) => ({
      person_id: `ocd-person/d-${startIdx + i}`,
      option,
    }));
  }

  it("rates Alice 100% loyal when she always votes with Democratic majority", () => {
    const idx = new Map([...fixturePeopleIndex, ...FILLER_INDEX]);
    const bills: FixtureBill[] = Array.from({ length: 25 }, (_, i) => ({
      id: `b${i}`,
      subjects: [],
      chamber_progress: { lower: null, upper: null, governor: null },
      actions: [],
      current_status: "",
      sponsors: [],
      votes: [
        {
          chamber: "lower",
          member_votes: [
            { person_id: ALICE_OCD, option: "yes" },
            ...dvote("yes", 0, 20),
            ...dvote("no", 20, 5),
          ],
        },
      ],
    }));

    const stats = computeStatsFromFixture(bills, [ALICE, BOB, ...FILLER], idx);
    expect(stats.get("ky-alice")!.partyLoyaltyRate).toBeCloseTo(1.0);
  });

  it("suppresses loyalty rate when votesParticipated < LOYALTY_MIN_N", () => {
    const idx = new Map([...fixturePeopleIndex, ...FILLER_INDEX]);
    const bills: FixtureBill[] = [
      {
        id: "b1",
        subjects: [],
        chamber_progress: { lower: null, upper: null, governor: null },
        actions: [],
        current_status: "",
        sponsors: [],
        votes: [
          {
            chamber: "lower",
            member_votes: [
              { person_id: ALICE_OCD, option: "yes" },
              ...dvote("yes", 0, 20),
            ],
          },
        ],
      },
    ];
    const stats = computeStatsFromFixture(bills, [ALICE, BOB, ...FILLER], idx);
    expect(stats.get("ky-alice")!.partyLoyaltyRate).toBeNull();
  });

  it("returns null loyalty for legislators with no party", () => {
    const NEUTRAL: FixturePerson = { id: "ky-neutral", chamber: "lower", party: null };
    const NEUTRAL_OCD = "ocd-person/neutral";
    const idx = new Map([...fixturePeopleIndex, [NEUTRAL_OCD, NEUTRAL.id]]);
    const bills: FixtureBill[] = Array.from({ length: 25 }, (_, i) => ({
      id: `b${i}`,
      subjects: [],
      chamber_progress: { lower: null, upper: null, governor: null },
      actions: [],
      current_status: "",
      sponsors: [],
      votes: [{ chamber: "lower", member_votes: [{ person_id: NEUTRAL_OCD, option: "yes" }] }],
    }));
    const stats = computeStatsFromFixture(bills, [NEUTRAL], idx);
    expect(stats.get("ky-neutral")!.partyLoyaltyRate).toBeNull();
  });
});
