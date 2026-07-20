"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  ChevronsUpDown,
  ClipboardCheck,
  LayoutDashboard,
  LogOut,
  Radar,
  Settings,
  ShieldAlert,
  ShieldPlus,
  Swords,
  Target as TargetIcon,
} from "lucide-react";

import {
  Avatar,
  AvatarFallback,
} from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import {
  currentUser,
  dashboardStats,
  liveSweep,
  organizations,
} from "@/lib/mock-data";

const NAV_ITEMS = [
  { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { title: "Targets", href: "/targets", icon: TargetIcon },
  { title: "Launch Campaign", href: "/campaigns/new", icon: Swords },
  { title: "Findings", href: "/findings", icon: ShieldAlert, badge: dashboardStats.openFindings },
  { title: "Review Queue", href: "/review", icon: ClipboardCheck, badge: dashboardStats.pendingReview },
];

function OrgSwitcher() {
  const [org, setOrg] = useState(organizations[0]);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <SidebarMenuButton
            size="lg"
            className="data-[state=open]:bg-sidebar-accent"
          />
        }
      >
        <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <ShieldPlus className="size-4" />
        </div>
        <div className="flex flex-1 flex-col text-left leading-tight">
          <span className="truncate text-sm font-semibold">{org.name}</span>
          <span className="truncate text-xs text-muted-foreground capitalize">
            {org.plan} plan
          </span>
        </div>
        <ChevronsUpDown className="size-4 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <DropdownMenuLabel className="text-xs text-muted-foreground">
          Organizations
        </DropdownMenuLabel>
        {organizations.map((o) => (
          <DropdownMenuItem
            key={o.id}
            onClick={() => setOrg(o)}
            className="gap-2"
          >
            <div className="flex size-6 items-center justify-center rounded bg-muted">
              <ShieldPlus className="size-3.5" />
            </div>
            <span className="flex-1 truncate">{o.name}</span>
            {o.id === org.id && (
              <span className="size-1.5 rounded-full bg-primary" />
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function NavUser() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <SidebarMenuButton
            size="lg"
            className="data-[state=open]:bg-sidebar-accent"
          />
        }
      >
        <Avatar className="size-8 rounded-md">
          <AvatarFallback className="rounded-md bg-primary/10 text-primary">
            {currentUser.initials}
          </AvatarFallback>
        </Avatar>
        <div className="flex flex-1 flex-col text-left leading-tight">
          <span className="truncate text-sm font-medium">
            {currentUser.name}
          </span>
          <span className="truncate text-xs text-muted-foreground">
            {currentUser.email}
          </span>
        </div>
        <ChevronsUpDown className="size-4 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" side="top" className="w-56">
        <DropdownMenuLabel className="flex items-center gap-2">
          <Avatar className="size-8 rounded-md">
            <AvatarFallback className="rounded-md bg-primary/10 text-primary">
              {currentUser.initials}
            </AvatarFallback>
          </Avatar>
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-medium">{currentUser.name}</span>
            <span className="text-xs font-normal text-muted-foreground capitalize">
              {currentUser.role}
            </span>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem>
          <Settings className="size-4" /> Settings
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem render={<Link href="/login" />}>
          <LogOut className="size-4" /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppSidebar() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <OrgSwitcher />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Platform</SidebarGroupLabel>
          <SidebarMenu>
            {NAV_ITEMS.map((item) => (
              <SidebarMenuItem key={item.href}>
                <SidebarMenuButton
                  render={<Link href={item.href} />}
                  isActive={isActive(item.href)}
                  tooltip={item.title}
                >
                  <item.icon />
                  <span>{item.title}</span>
                </SidebarMenuButton>
                {item.badge ? (
                  <SidebarMenuBadge>{item.badge}</SidebarMenuBadge>
                ) : null}
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Live</SidebarGroupLabel>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                render={<Link href={`/sweeps/${liveSweep.id}`} />}
                isActive={isActive(`/sweeps/${liveSweep.id}`)}
                tooltip="Active sweep"
              >
                <Radar className={cn(liveSweep.status === "running" && "text-sky-400")} />
                <span>Active Sweep</span>
              </SidebarMenuButton>
              {liveSweep.status === "running" ? (
                <SidebarMenuBadge>
                  <Badge
                    variant="outline"
                    className="border-sky-500/30 bg-sky-500/15 px-1.5 text-[10px] text-sky-400"
                  >
                    live
                  </Badge>
                </SidebarMenuBadge>
              ) : null}
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <NavUser />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
