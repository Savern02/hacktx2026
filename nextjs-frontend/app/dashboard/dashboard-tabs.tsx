"use client";

import { FileText, LayoutDashboard, LogOut, Settings } from "lucide-react";

import { logout } from "@/components/actions/logout-action";
import {
  DashboardSidebar,
  type SidebarTab,
} from "@/components/dashboard/sidebar";
import { EquaChat } from "@/components/dashboard/equa-chat";
import { SafeToSpendRing } from "@/components/dashboard/safe-to-spend-ring";
import { SettingsTab } from "@/components/dashboard/settings-tab";
import { MoneyCheckup } from "@/components/dashboard/money-checkup";
import { ProgramMatches } from "@/components/dashboard/program-matches";
import {
  StatusProgressBar,
  type ProgressStatus,
} from "@/components/dashboard/status-progress-bar";

// Placeholder data until the Nessie/Snowflake endpoints exist.
// Mock government benefit applications until the backend tracks real ones.
const SAMPLE_APPLICATIONS: {
  id: string;
  name: string;
  description: string;
  status: ProgressStatus;
}[] = [
  {
    id: "snap",
    name: "SNAP",
    description: "Monthly food assistance on an EBT card",
    status: "in-progress",
  },
  {
    id: "liheap",
    name: "LIHEAP",
    description: "Help paying heating and electric bills",
    status: "in-progress",
  },
  {
    id: "medicaid",
    name: "Medicaid",
    description: "Free or low-cost health coverage",
    status: "complete",
  },
  {
    id: "lifeline",
    name: "Lifeline",
    description: "Discount on phone or internet service",
    status: "complete",
  },
  {
    id: "wic",
    name: "WIC",
    description: "Food and nutrition support for parents and young children",
    status: "in-progress",
  },
];

function OverviewTab() {
  return (
    <div className="grid gap-6">
      <SafeToSpendRing />
      <MoneyCheckup />
    </div>
  );
}

function ProgramsTab() {
  return (
    <div className="grid gap-8">
      <section className="grid gap-4">
        <h2 className="text-lg font-semibold">Your applications</h2>
        <ul className="grid gap-3 md:grid-cols-2">
          {SAMPLE_APPLICATIONS.map((app) => (
            <li key={app.id} className="rounded-lg border bg-card p-4">
              <StatusProgressBar status={app.status} label={app.name} />
              <p className="mt-2 text-sm text-muted-foreground">
                {app.description}
              </p>
            </li>
          ))}
        </ul>
      </section>
      <ProgramMatches />
    </div>
  );
}

const TABS: SidebarTab[] = [
  {
    id: "overview",
    label: "Overview",
    icon: LayoutDashboard,
    content: <OverviewTab />,
  },
  {
    id: "programs",
    label: "Programs",
    icon: FileText,
    content: <ProgramsTab />,
  },
  {
    id: "settings",
    label: "Settings",
    icon: Settings,
    content: <SettingsTab />,
  },
];

export function DashboardTabs() {
  return (
    <DashboardSidebar
      title="Equa"
      titleHref="/"
      chat={<EquaChat />}
      tabs={TABS}
      footer={
        <button
          type="button"
          onClick={() => logout()}
          aria-label="Log out"
          title="Log out"
          className="flex min-h-11 w-full items-center gap-3 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground md:group-data-[collapsed=true]:justify-center md:group-data-[collapsed=true]:px-0"
        >
          <LogOut className="h-5 w-5 shrink-0" aria-hidden="true" />
          <span className="md:group-data-[collapsed=true]:hidden">Log out</span>
        </button>
      }
    />
  );
}
