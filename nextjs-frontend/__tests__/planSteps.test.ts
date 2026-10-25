import type { AprImpact, ProgramMatches } from "@/app/clientService";
import { buildPlanSteps } from "@/components/dashboard/plan-tab";

const program = (
  id: number,
  name: string,
  status: "in-progress" | "complete" = "in-progress",
) => ({
  program: {
    id,
    name,
    jurisdiction: "Federal",
    level: "federal",
    administering_agency: null,
    categories: [],
    summary: null,
    eligibility_summary: null,
    how_to_apply: null,
    apply_url: null,
    info_url: null,
    phone: null,
  },
  reason: `${name} fits your situation.`,
  confidence: 0.7,
  application_url: `https://example.gov/${id}`,
  application_status: status,
});

const impact: AprImpact = {
  loans: [],
  highest: {
    name: "Toyota auto loan",
    lender: "Toyota",
    type: "auto",
    apr: 19.42,
    apr_basis: "Estimated from a 590 credit score",
    balance: 14200,
    monthly_payment: 389,
    monthly_interest: 229.8,
  },
  utility_monthly: 105,
  payoff_with_utility_help: {
    extra_monthly: 105,
    months_now: 56,
    months_with_extra: 39,
    months_sooner: 17,
    interest_saved: 2400,
  },
  utility_program: program(1, "Low-Income Home Energy Assistance"),
};

const matches: ProgramMatches = {
  summary: "",
  computed_at: "",
  matches: [
    program(1, "Low-Income Home Energy Assistance"), // already the utility step
    program(2, "SNAP"),
    program(3, "Section 8", "complete"), // finished: goes to Completed
  ],
};

describe("buildPlanSteps", () => {
  it("builds the plan from the user's real data, in order, without repeats", () => {
    const steps = buildPlanSteps(impact, matches);
    expect(steps.map((s) => s.id)).toEqual([
      "program-1",
      "lender-rate",
      "program-2",
      "program-3",
    ]);
    // Finished applications stay in the plan, marked done (for the Completed drawer).
    expect(steps.map((s) => Boolean(s.done))).toEqual([
      false,
      false,
      false,
      true,
    ]);
    expect(steps[0].programId).toBe(1);
    expect(steps[0].impact).toContain("17 months sooner");
    expect(steps[0].link?.href).toBe("https://example.gov/1");
    expect(steps[1].title).toBe("Ask Toyota for a lower rate.");
    expect(steps[1].impact).toContain("19.42% APR");
    expect(steps[2].impact).toBe("SNAP fits your situation.");
  });

  it("takes the utility step's status from the latest matches", () => {
    const done = {
      ...matches,
      matches: [program(1, "Low-Income Home Energy Assistance", "complete")],
    };
    expect(buildPlanSteps(impact, done)[0].done).toBe(true);
  });

  it("is empty before any data arrives", () => {
    expect(buildPlanSteps(null, null)).toEqual([]);
  });
});
