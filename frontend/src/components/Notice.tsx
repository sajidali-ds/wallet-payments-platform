import type { ReactNode } from "react";

interface NoticeProps {
  kind: "error" | "success" | "warning";
  children: ReactNode;
}

// Errors are announced immediately (role="alert"); success and warnings politely (role="status").
export function Notice({ kind, children }: NoticeProps) {
  return (
    <div className={`notice notice-${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}
