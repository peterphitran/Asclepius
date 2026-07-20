"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Plus } from "lucide-react";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";

const SEGMENT_LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  targets: "Targets",
  campaigns: "Campaigns",
  new: "Launch Campaign",
  findings: "Findings",
  review: "Review Queue",
  sweeps: "Sweeps",
};

function labelFor(segment: string) {
  return SEGMENT_LABELS[segment] ?? segment.replace(/-/g, " ");
}

export function AppHeader() {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);

  return (
    <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-1 h-5!" />

      <Breadcrumb>
        <BreadcrumbList>
          {segments.map((segment, i) => {
            const href = `/${segments.slice(0, i + 1).join("/")}`;
            const isLast = i === segments.length - 1;
            return (
              <div key={href} className="flex items-center gap-1.5">
                {i > 0 && <BreadcrumbSeparator />}
                <BreadcrumbItem>
                  {isLast ? (
                    <BreadcrumbPage>{labelFor(segment)}</BreadcrumbPage>
                  ) : (
                    <BreadcrumbLink render={<Link href={href} />}>
                      {labelFor(segment)}
                    </BreadcrumbLink>
                  )}
                </BreadcrumbItem>
              </div>
            );
          })}
        </BreadcrumbList>
      </Breadcrumb>

      <div className="ml-auto flex items-center gap-2">
        <Button
          render={<Link href="/campaigns/new" />}
          nativeButton={false}
          size="sm"
        >
          <Plus className="size-4" />
          <span className="hidden sm:inline">Launch Campaign</span>
        </Button>
      </div>
    </header>
  );
}
