import { describe, it, expect } from "vitest";
import { slugifySubject, subjectFromSlug } from "./topics";
import { FEATURED_SUBJECTS } from "./featured-subjects";

describe("slugifySubject", () => {
  it("kebab-cases punctuation and spaces", () => {
    expect(slugifySubject("Education, Elementary And Secondary")).toBe("education-elementary-and-secondary");
    expect(slugifySubject("Crimes And Punishments")).toBe("crimes-and-punishments");
    expect(slugifySubject("  Local  Government  ")).toBe("local-government");
  });

  it("round-trips every featured subject via subjectFromSlug", () => {
    for (const subject of FEATURED_SUBJECTS) {
      const slug = slugifySubject(subject);
      expect(subjectFromSlug(slug)).toBe(subject);
    }
  });

  it("returns null for unknown slugs", () => {
    expect(subjectFromSlug("unknown-topic")).toBeNull();
    expect(subjectFromSlug("")).toBeNull();
  });
});
