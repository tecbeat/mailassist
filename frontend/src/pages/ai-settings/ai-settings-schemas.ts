import { z } from "zod/v4";

// ---------------------------------------------------------------------------
// Zod schema for AI provider form
// ---------------------------------------------------------------------------

export const aiProviderSchema = z.object({
  name: z.string().max(100).optional().or(z.literal("")),
  provider_type: z.enum(["openai", "ollama"]),
  base_url: z.string().min(1, "Base URL is required").max(500),
  model_name: z.string().min(1, "Model name is required").max(100),
  api_key: z.string().optional().or(z.literal("")),
  temperature: z.number().min(0).max(2),
  max_tokens: z.number().int().min(64).max(32768),
  timeout_seconds: z.number().int().min(5).max(600).nullable().optional(),
});

export type AIProviderFormValues = z.infer<typeof aiProviderSchema>;

/** Provider-specific default values for temperature and max_tokens. */
export const PROVIDER_DEFAULTS: Record<
  "openai" | "ollama",
  { temperature: number; max_tokens: number; base_url: string; model_name: string }
> = {
  openai: {
    temperature: 0.3,
    max_tokens: 1024,
    base_url: "https://api.openai.com/v1",
    model_name: "gpt-4o",
  },
  ollama: {
    temperature: 0.7,
    max_tokens: 4096,
    base_url: "http://localhost:11434",
    model_name: "llama3.1",
  },
};

export function getDefaultFormValues(providerType: "openai" | "ollama" = "openai"): AIProviderFormValues {
  const defaults = PROVIDER_DEFAULTS[providerType];
  return {
    name: "",
    provider_type: providerType,
    base_url: defaults.base_url,
    model_name: defaults.model_name,
    api_key: "",
    temperature: defaults.temperature,
    max_tokens: defaults.max_tokens,
    timeout_seconds: null,
  };
}

export function providerTypeLabel(type: string): string {
  switch (type) {
    case "openai":
      return "OpenAI";
    case "ollama":
      return "Ollama";
    default:
      return type.charAt(0).toUpperCase() + type.slice(1);
  }
}
