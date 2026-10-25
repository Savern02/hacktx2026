"use client";

import { useState } from "react";
import Image from "next/image";
import {
  Car,
  FileText,
  LayoutDashboard,
  LogOut,
  Route,
  Settings,
} from "lucide-react";

import logo from "@/app/equity-fintech.png";

import { logout } from "@/components/actions/logout-action";
import {
  DashboardSidebar,
  type SidebarTab,
} from "@/components/dashboard/sidebar";
import { EquaChat } from "@/components/dashboard/equa-chat";
import { AprDashboard } from "@/components/dashboard/apr-dashboard";
import { SafeToSpendRing } from "@/components/dashboard/safe-to-spend-ring";
import { clearCache } from "@/lib/data-cache";
import { PlanTab } from "@/components/dashboard/plan-tab";
import { ToyotaTab } from "@/components/dashboard/toyota-tab";
import { SettingsTab } from "@/components/dashboard/settings-tab";
import { MoneyCheckup } from "@/components/dashboard/money-checkup";
import { ProgramMatches } from "@/components/dashboard/program-matches";

function OverviewTab() {
  return (
    // One centered column: easier to read, especially on phones.
    <div className="mx-auto grid w-full max-w-3xl gap-8 text-center">
      <SafeToSpendRing />
      <MoneyCheckup />
      <AprDashboard />
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
    id: "plan",
    label: "Plan",
    icon: Route,
    content: <PlanTab />,
  },
  {
    id: "toyota",
    label: "My Toyota",
    icon: Car,
    content: <ToyotaTab />,
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
  // A fresh dashboard load (e.g. after logging in) starts with an empty cache,
  // so one user never sees another's data. Switching tabs keeps it.
  useState(clearCache);

  return (
    <DashboardSidebar
      title="Equa"
      titleHref="/"
      titleIcon={
        <Image src={logo} alt="" className="h-7 w-7 shrink-0 dark:invert" />
      }
      chat={<EquaChat />}
      tabs={TABS}
      footer={
        <button
          type="button"
          onClick={() => {
            clearCache();
            logout();
          }}
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
