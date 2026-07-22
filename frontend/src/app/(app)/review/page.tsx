import { ClipboardCheck } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";

export default function ReviewQueuePage() {
  return (
    <ComingSoon
      title="Review Queue"
      description="The human-in-the-loop gate: approve or reject critical findings before disclosure."
      icon={ClipboardCheck}
      note="Next: a queue of pending critical findings with side-by-side evidence and approve / reject actions that mirror responsible-disclosure workflows."
    />
  );
}
