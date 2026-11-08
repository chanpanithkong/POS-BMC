"use client";

import { useRouter } from "next/navigation";
import { type Column, DataTable } from "@/components/shared/data-table";
import { PageHeader, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { formatDateTime, titleCase } from "@/lib/format";
import { notificationsApi } from "@/services";
import type { AppNotification } from "@/types";

export default function NotificationsPage() {
  const router = useRouter();
  const query = useApiQuery(["notifications"], notificationsApi.list);
  const read = useApiMutation((ids?: string[]) => notificationsApi.markRead(ids));
  const columns: Column<AppNotification>[] = [
    { id: "at", header: "When", value: (n) => n.createdAt, cell: (n) => <span className="whitespace-nowrap">{formatDateTime(n.createdAt)}</span> },
    { id: "kind", header: "Type", value: (n) => titleCase(n.kind), hideBelow: "md" },
    { id: "title", header: "Title", value: (n) => n.title, className: "font-medium" },
    { id: "message", header: "Message", value: (n) => n.message, hideBelow: "lg", className: "max-w-md truncate" },
    { id: "read", header: "State", value: (n) => (n.read ? "Read" : "Unread"), cell: (n) => <StatusBadge status={n.read ? "CLOSED" : "OPEN"} /> },
  ];
  return (
    <>
      <PageHeader title="Notifications" actions={<Button size="sm" variant="outline" onClick={() => void read.fire(undefined)}>Mark all read</Button>} />
      <DataTable data={query.data} columns={columns} getRowId={(n) => n.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} searchPlaceholder="Search notifications" emptyTitle="No notifications"
        onRowClick={(n) => { void read.fire([n.id]); if (n.link) router.push(n.link); }}
        filters={[{ id: "read", label: "States", options: [{ value: "Unread", label: "Unread" }, { value: "Read", label: "Read" }], value: (n) => (n.read ? "Read" : "Unread") }]} />
    </>
  );
}
