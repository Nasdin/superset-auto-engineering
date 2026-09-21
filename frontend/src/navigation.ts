import {
  ChartNoAxesColumn,
  Workflow,
  Settings,
  FileCheck2,
} from "lucide-react";

export const sections = [
  {
    name: "Evidence",
    icon: FileCheck2,
    description: "Review the proof",
    views: [
      {
        page: "Release validation",
        label: "Release validation",
        slug: "evidence",
      },
      {
        page: "Recorded demos",
        label: "Recorded demos",
        slug: "recorded-demos",
      },
      { page: "PR evidence", label: "PR evidence", slug: "pull-requests" },
      { page: "Repository graph", label: "Repository graph", slug: "lineage" },
    ],
  },
  {
    name: "Workflows",
    icon: Workflow,
    description: "Follow the work",
    views: [
      { page: "Workflows", label: "Workflow lanes", slug: "workflows" },
      {
        page: "Schedules & triggers",
        label: "Automations",
        slug: "automations",
      },
      { page: "Learning & memory", label: "Learning", slug: "learning" },
      { page: "Devin runs", label: "Devin runs", slug: "runs" },
      {
        page: "Dependabot runs",
        label: "Dependabot runs",
        slug: "dependencies",
      },
    ],
  },
  {
    name: "Analytics",
    icon: ChartNoAxesColumn,
    description: "Measure the change",
    views: [{ page: "Analytics", label: "Analytics", slug: "analytics" }],
  },
  {
    name: "System",
    icon: Settings,
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
