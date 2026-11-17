import { describe, expect, it } from "vitest";
import { ApiError, describeError } from "../api";

describe("error messages", () => {
  it("explains plan limits and license refusals in plain words", () => {
    expect(describeError(new ApiError(403, "entitlement_denied", "x", { limit: "watchlists" }))).toContain("watchlists");
    expect(describeError(new ApiError(403, "license_denied", "x"))).toBe("The data license does not permit this use.");
    expect(describeError(new ApiError(402, "quota_exceeded", "x"))).toContain("resets");
  });
  it("names the first invalid field", () => {
    const error = new ApiError(422, "validation_failed", "x", { issues: [{ field: "name", problem: "Field required" }] });
    expect(describeError(error)).toBe("name: Field required");
  });
  it("covers network failures", () => {
    expect(describeError(new TypeError("fetch failed"))).toContain("could not be reached");
  });
});
