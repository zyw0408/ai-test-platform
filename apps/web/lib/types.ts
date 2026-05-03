import type {
  Artifact,
  Project,
  SourceSpec,
  TestCase,
  TestRun,
} from "@ai-test-platform/shared-schema";

export type DashboardSnapshot = {
  projects: Project[];
  specs: SourceSpec[];
  cases: TestCase[];
  runs: TestRun[];
  artifacts: Artifact[];
};
