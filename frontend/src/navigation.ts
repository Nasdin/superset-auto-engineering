import { Activity, GitPullRequest, Settings2, ShieldCheck } from "lucide-react";

export const sections = [
  {
    name: "Evidence",
    icon: ShieldCheck,
    description: "Review the proof",
    views: [
      {
        page: "Release validation",
        label: "Release validation",
        slug: "evidence",
      },
      { page: "PR evidence", label: "PR evidence", slug: "pull-requests" },
      { page: "Repository graph", label: "Repository graph", slug: "lineage" },
    ],
  },
  {
    name: "Workflows",
    icon: GitPullRequest,
    description: "Follow the work",
    views: [
      { page: "Workflows", label: "Workflow lanes", slug: "workflows" },
      { page: "Devin runs", label: "Devin runs", slug: "runs" },
      {
        page: "Dependabot runs",
        label: "Dependabot runs",
        slug: "dependencies",
      },
      {
        page: "Learning & memory",
        label: "Learning & memory",
        slug: "learning",
      },
    ],
  },
  {
    name: "Analytics",
    icon: Activity,
    description: "Measure the change",
    views: [{ page: "Analytics", label: "Analytics", slug: "analytics" }],
  },
  {
    name: "Operations",
    icon: Settings2,
    description: "Connections & limits",
    views: [
      { page: "Live operations", label: "Live operations", slug: "operations" },
    ],
  },
] as const;
export type Page = (typeof sections)[number]["views"][number]["page"];
export const views = sections.flatMap((section) => [...section.views]);
export function pageFromHash(): Page {
  return (
    views.find((view) => `#${view.slug}` === window.location.hash)?.page ||
    "Release validation"
  );
}
