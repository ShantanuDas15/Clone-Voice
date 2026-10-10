import type { Metadata } from "next";

import { PageHeader } from "@/components/ui/page-header";
import { HistoryList } from "@/components/history-list";

export const metadata: Metadata = { title: "History" };

export default function HistoryPage() {
  return (
    <section className="max-w-xl">
      <PageHeader title="History">Replay or download what you have generated.</PageHeader>
      <HistoryList />
    </section>
  );
}
