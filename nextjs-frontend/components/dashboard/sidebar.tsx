"use client";

import * as React from "react";
import Link from "next/link";
import {
  LayoutList,
  Menu,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
  X,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

export type SidebarTab = {
  id: string;
  label: string;
  icon: LucideIcon;
  content: React.ReactNode;
};

export type DashboardSidebarProps = {
  tabs: SidebarTab[];
  /** Tab shown first. Falls back to the first tab. */
  defaultTabId?: string;
  /** Optional heading shown at the top of the sidebar. */
  title?: string;
  /** When set, the title links here (e.g. the homepage). */
  titleHref?: string;
  /** Pinned below the tabs (e.g. a logout button). Use `md:group-data-[collapsed=true]:hidden` to hide text in the collapsed rail. */
  footer?: React.ReactNode;
  /** Chat panel. When set, a button next to the title turns the sidebar into this chat space. */
  chat?: React.ReactNode;
  /** Name of the chat mode, used for button labels. */
  chatLabel?: string;
  className?: string;
};

const iconButton =
  "inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function DashboardSidebar({
  tabs,
  defaultTabId,
  title = "Menu",
  titleHref,
  footer,
  chat,
  chatLabel = "Equa mode",
  className,
}: DashboardSidebarProps) {
  const [activeId, setActiveId] = React.useState(
    defaultTabId ?? tabs[0]?.id ?? "",
  );
  // Mobile drawer open state (ignored at md and up).
  const [mobileOpen, setMobileOpen] = React.useState(false);
  // Desktop rail collapse state (ignored below md).
  const [collapsed, setCollapsed] = React.useState(false);
  // Chat mode swaps the tab list for the chat panel.
  const [chatMode, setChatMode] = React.useState(false);
  // Keep the chat mounted after first open so the conversation survives toggling.
  const [chatMounted, setChatMounted] = React.useState(false);
  const rail = collapsed && !chatMode;

  const navId = React.useId();
  const menuButtonRef = React.useRef<HTMLButtonElement>(null);
  const closeButtonRef = React.useRef<HTMLButtonElement>(null);

  const activeTab = tabs.find((t) => t.id === activeId) ?? tabs[0];

  const closeMobile = React.useCallback(() => {
    setMobileOpen(false);
    menuButtonRef.current?.focus();
  }, []);

  // Escape closes the drawer; lock body scroll while it is open.
  React.useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeMobile();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [mobileOpen, closeMobile]);

  // If the viewport grows to md while the drawer is open, reset it.
  React.useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const onChange = () => {
      if (mq.matches) setMobileOpen(false);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggleChat = () => {
    setChatMode(!chatMode);
    setChatMounted(true);
    setCollapsed(false);
  };

  const selectTab = (id: string) => {
    setActiveId(id);
    if (mobileOpen) closeMobile();
  };

  return (
    <div className={cn("flex w-full min-w-0 flex-col md:flex-row", className)}>
      {/* Mobile top bar */}
      <div className="sticky top-0 z-30 flex items-center gap-2 border-b bg-background px-2 py-1 md:hidden">
        <button
          ref={menuButtonRef}
          type="button"
          className={iconButton}
          aria-label="Open navigation menu"
          aria-expanded={mobileOpen}
          aria-controls={navId}
          onClick={() => {
            setChatMode(false);
            setMobileOpen(true);
          }}
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </button>
        <span className="truncate text-base font-semibold">
          {activeTab?.label}
        </span>
        {chat ? (
          <button
            type="button"
            className={cn(iconButton, "ml-auto")}
            aria-label={`Open ${chatLabel}`}
            onClick={() => {
              setChatMode(true);
              setChatMounted(true);
              setMobileOpen(true);
            }}
          >
            <MessageCircle className="h-5 w-5" aria-hidden="true" />
          </button>
        ) : null}
      </div>

      {/* Mobile backdrop */}
      <div
        aria-hidden="true"
        onClick={closeMobile}
        className={cn(
          "fixed inset-0 z-40 bg-black/50 transition-opacity duration-200 md:hidden",
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0",
        )}
      />

      {/* Sidebar: drawer on mobile, persistent rail on md+ */}
      <aside
        id={navId}
        aria-label="Dashboard navigation"
        data-collapsed={rail}
        className={cn(
          "group fixed inset-y-0 left-0 z-50 flex flex-col border-r bg-background shadow-lg",
          chatMode ? "w-full" : "w-72 max-w-[85vw]",
          "transition-[transform,width,visibility] duration-200 ease-in-out",
          mobileOpen ? "visible translate-x-0" : "invisible -translate-x-full",
          "md:visible md:sticky md:top-0 md:z-auto md:h-screen md:max-w-none md:translate-x-0 md:shadow-none",
          chatMode ? "md:w-96" : rail ? "md:w-[4.25rem]" : "md:w-64",
        )}
      >
        <div
          className={cn(
            "flex items-center gap-2 border-b px-3 py-2",
            rail && "md:flex-col md:px-2",
          )}
        >
          {titleHref ? (
            <Link
              href={titleHref}
              className={cn(
                "flex min-h-11 flex-1 items-center truncate rounded-md font-semibold hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                rail && "md:hidden",
              )}
            >
              {title}
            </Link>
          ) : (
            <span
              className={cn(
                "flex-1 truncate font-semibold",
                rail && "md:hidden",
              )}
            >
              {title}
            </span>
          )}
          {chat ? (
            <button
              type="button"
              className={cn(
                iconButton,
                chatMode &&
                  "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground",
              )}
              aria-pressed={chatMode}
              aria-label={chatMode ? "Back to menu" : `Turn on ${chatLabel}`}
              title={chatMode ? "Back to menu" : chatLabel}
              onClick={toggleChat}
            >
              {chatMode ? (
                <LayoutList className="h-5 w-5" aria-hidden="true" />
              ) : (
                <MessageCircle className="h-5 w-5" aria-hidden="true" />
              )}
            </button>
          ) : null}
          <button
            ref={closeButtonRef}
            type="button"
            className={cn(iconButton, "md:hidden")}
            aria-label="Close navigation menu"
            onClick={closeMobile}
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
          <button
            type="button"
            className={cn(iconButton, "hidden", !chatMode && "md:inline-flex")}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
            aria-controls={navId}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() => setCollapsed((c) => !c)}
          >
            {collapsed ? (
              <PanelLeftOpen className="h-5 w-5" aria-hidden="true" />
            ) : (
              <PanelLeftClose className="h-5 w-5" aria-hidden="true" />
            )}
          </button>
        </div>

        {chatMounted ? (
          <div
            className={cn(
              "flex min-h-0 flex-1 flex-col",
              !chatMode && "hidden",
            )}
          >
            {chat}
          </div>
        ) : null}
        {chatMode ? null : (
          <>
            <nav className="flex-1 overflow-y-auto overflow-x-hidden p-2">
              <ul className="flex flex-col gap-1">
                {tabs.map((tab) => {
                  const Icon = tab.icon;
                  const active = tab.id === activeTab?.id;
                  return (
                    <li key={tab.id}>
                      <button
                        type="button"
                        onClick={() => selectTab(tab.id)}
                        aria-current={active ? "page" : undefined}
                        aria-label={tab.label}
                        title={rail ? tab.label : undefined}
                        className={cn(
                          "flex min-h-11 w-full items-center gap-3 rounded-md px-3 text-left text-sm font-medium transition-colors",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          active
                            ? "bg-primary text-primary-foreground"
                            : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                          rail && "md:justify-center md:px-0",
                        )}
                      >
                        <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
                        <span className={cn("truncate", rail && "md:hidden")}>
                          {tab.label}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </nav>

            {footer ? <div className="border-t p-2">{footer}</div> : null}
          </>
        )}
      </aside>

      {/* Active tab content */}
      <section
        aria-label={activeTab?.label}
        className="min-w-0 flex-1 p-4 md:p-6 lg:p-8"
      >
        {activeTab?.content}
      </section>
    </div>
  );
}
