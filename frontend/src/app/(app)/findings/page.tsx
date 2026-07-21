import { ShieldAlert } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";

export default function FindingsPage() {
  return (
    <ComingSoon
      title="Findings"
      description="Every confirmed vulnerability across your targets, filterable by severity and category."
      icon={ShieldAlert}
      note="Next: a filterable, sortable table of findings with severity, category, target, status, and confidence — each row linking to a full report."
    />
  );
}
