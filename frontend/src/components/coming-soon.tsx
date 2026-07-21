import type { LucideIcon } from "lucide-react";

export function ComingSoon({
  title,
  description,
  icon: Icon,
  note,
}: {
  title: string;
  description: string;
  icon: LucideIcon;
  note?: string;
}) {
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed py-20 text-center">
        <div className="flex size-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
          <Icon className="size-6" />
        </div>
        <div className="max-w-sm">
          <p className="font-medium">This screen is up next</p>
          <p className="text-sm text-muted-foreground">
            {note ??
              "We'll build this out in the next increment, wired to the same mock data model."}
          </p>
        </div>
      </div>
    </div>
  );
}
