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

// Placeholder data until the Nessie/Snowflake endpoints exist.
function OverviewTab() {
  return (
    <div className="grid gap-6">
      <SafeToSpendRing />
      <MoneyCheckup />
    </div>
  );
}

function ProgramsTab() {
  return <ProgramMatches />;
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
