import { FileText } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";

export default function FindingDetailPage() {
  return (
    <ComingSoon
      title="Report Detail"
      description="The full vulnerability report produced by the Reporter agent."
      icon={FileText}
      note="Next: attack description, reproduction steps, patient-safety impact, the attack prompt and target response, and recommended remediation."
    />
  );
}
