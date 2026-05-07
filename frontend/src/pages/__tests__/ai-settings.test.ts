import { describe, it, expect } from "vitest";

import {
  aiProviderSchema,
  PROVIDER_DEFAULTS,
  getDefaultFormValues,
  providerTypeLabel,
} from "@/pages/ai-settings/ai-settings-schemas";

describe("ai-settings-schemas", () => {
  describe("aiProviderSchema", () => {
    it("accepts anthropic as provider_type", () => {
      const result = aiProviderSchema.safeParse({
        provider_type: "anthropic",
        base_url: "https://api.anthropic.com",
        model_name: "claude-sonnet-4-20250514",
        temperature: 0.3,
        max_tokens: 4096,
      });
      expect(result.success).toBe(true);
    });

    it("rejects invalid provider_type", () => {
      const result = aiProviderSchema.safeParse({
        provider_type: "invalid",
        base_url: "http://example.com",
        model_name: "model",
        temperature: 0.3,
        max_tokens: 1024,
      });
      expect(result.success).toBe(false);
    });
  });

  describe("PROVIDER_DEFAULTS", () => {
    it("has anthropic defaults", () => {
      expect(PROVIDER_DEFAULTS.anthropic).toEqual({
        temperature: 0.3,
        max_tokens: 4096,
        base_url: "https://api.anthropic.com",
        model_name: "claude-sonnet-4-20250514",
      });
    });
  });

  describe("getDefaultFormValues", () => {
    it("returns anthropic defaults", () => {
      const values = getDefaultFormValues("anthropic");
      expect(values.provider_type).toBe("anthropic");
      expect(values.base_url).toBe("https://api.anthropic.com");
      expect(values.model_name).toBe("claude-sonnet-4-20250514");
    });
  });

  describe("providerTypeLabel", () => {
    it("returns Anthropic for anthropic", () => {
      expect(providerTypeLabel("anthropic")).toBe("Anthropic");
    });
  });
});
