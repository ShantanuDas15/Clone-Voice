import type { Metadata } from "next";

import { HistoryList } from "@/components/history-list";

export const metadata: Metadata = { title: "History" };

export default function HistoryPage() {
  return (
    <section className="max-w-xl">
      <h1 className="mb-4 text-2xl font-bold">History</h1>
      <HistoryList />
    </section>
  );
}
