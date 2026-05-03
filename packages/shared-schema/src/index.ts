import { z } from "zod";

export const projectSchema = z.object({
  id: z.string(),
  name: z.string().min(1),
  description: z.string().default(""),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const sourceTypeSchema = z.enum(["url", "file", "text"]);

export const sourceSpecSchema = z.object({
  id: z.string(),
  projectId: z.string(),
  sourceType: sourceTypeSchema,
  title: z.string(),
  location: z.string().default(""),
  content: z.string(),
  createdAt: z.string(),
});

export const testCaseKindSchema = z.enum(["api", "ui"]);
export const runStatusSchema = z.enum(["queued", "running", "passed", "failed"]);
export const runnerTypeSchema = z.enum(["api", "ui"]);

export const testCaseSchema = z.object({
  id: z.string(),
  projectId: z.string(),
  specId: z.string(),
  kind: testCaseKindSchema,
  title: z.string(),
  objective: z.string(),
  steps: z.array(z.string()),
  assertionHints: z.array(z.string()),
  payload: z.record(z.unknown()).default({}),
  createdAt: z.string(),
});

export const artifactSchema = z.object({
  id: z.string(),
  runId: z.string(),
  type: z.enum(["log", "trace", "screenshot", "report", "json"]),
  path: z.string(),
  label: z.string(),
});

export const testRunSchema = z.object({
  id: z.string(),
  projectId: z.string(),
  caseId: z.string(),
  runnerType: runnerTypeSchema,
  status: runStatusSchema,
  startedAt: z.string().nullable(),
  finishedAt: z.string().nullable(),
  summary: z.string().default(""),
  logs: z.array(z.string()).default([]),
  artifactIds: z.array(z.string()).default([]),
});

export const modelProviderConfigSchema = z.object({
  provider: z.string(),
  baseUrl: z.string().url().optional(),
  model: z.string(),
  apiKeyEnv: z.string(),
});

export const createProjectRequestSchema = z.object({
  name: z.string().min(1),
  description: z.string().default(""),
});

export const generateCasesRequestSchema = z.object({
  projectId: z.string(),
  specId: z.string(),
  kinds: z.array(testCaseKindSchema).default(["api", "ui"]),
});

export const createRunRequestSchema = z.object({
  projectId: z.string(),
  caseId: z.string(),
  runnerType: runnerTypeSchema,
});

export type Project = z.infer<typeof projectSchema>;
export type SourceSpec = z.infer<typeof sourceSpecSchema>;
export type TestCase = z.infer<typeof testCaseSchema>;
export type Artifact = z.infer<typeof artifactSchema>;
export type TestRun = z.infer<typeof testRunSchema>;
export type ModelProviderConfig = z.infer<typeof modelProviderConfigSchema>;
export type CreateProjectRequest = z.infer<typeof createProjectRequestSchema>;
export type GenerateCasesRequest = z.infer<typeof generateCasesRequestSchema>;
export type CreateRunRequest = z.infer<typeof createRunRequestSchema>;
