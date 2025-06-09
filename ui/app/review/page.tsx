// ui/app/review/page.tsx
"use client";

import { useEffect, useState } from "react";
import { supabase }                 from "@/lib/supabaseClient";

type ReviewRow = {
  id: string;
  product_slug: string;
  candidate_name: string;
  candidate_shop: string;
  fuzzy_score: number;
  semantic_score: number;
  raw_torob_data: string;    // JSON-stringified Torob result
  status: string;
  created_at: string;
};

export default function ReviewPage() {
  const [rows, setRows]     = useState<ReviewRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);

  // ─── fetch the “pending” queue rows ────────────────────────────────────────
  useEffect(() => {
    async function fetchQueue() {
      setLoading(true);
      const { data, error } = await supabase
        .from("review_queue")
        .select("*")
        .eq("status", "pending");

      if (error) setError(error.message);
      else      setRows(data || []);
      setLoading(false);
    }
    fetchQueue();
  }, []);

  if (loading) return <p className="p-4">Loading…</p>;
  if (error)   return <p className="p-4 text-red-600">Error: {error}</p>;

  return (
    <main className="p-4">
      <h1 className="text-2xl font-semibold mb-4">Review Queue</h1>
      {rows.length === 0
        ? <p>No items to review!</p>
        : (
          <ul className="space-y-4">
            {rows.map(row => (
              <li key={row.id} className="border rounded-lg p-4">
                <p><strong>Product:</strong> {row.product_slug}</p>
                <p>
                  <strong>Proposed:</strong> {row.candidate_name} (
                  {row.candidate_shop})
                </p>
                <p>
                  <strong>Fuzzy:</strong> {row.fuzzy_score.toFixed(2)},{" "}
                  <strong>Semantic:</strong> {row.semantic_score.toFixed(2)}
                </p>
                <div className="mt-2 flex space-x-2">
                  <button
                    className="px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700"
                    onClick={() => handleApprove(row)}
                  >
                    Approve
                  </button>
                  <button
                    className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
                    onClick={() => handleCorrect(row)}
                  >
                    Correct
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )
      }
    </main>
  );

  // ── Approve: parse raw_torob_data for true price & URL ────────────────────
  async function handleApprove(row: ReviewRow) {
    let torob: any;
    try {
      torob = JSON.parse(row.raw_torob_data);
    } catch {
      alert("Invalid raw data — cannot approve.");
      return;
    }

    const price = torob.price ?? 0;
    const url = torob.web_client_absolute_url
              || torob.more_info_url
              || "";

    const { error: insertErr } = await supabase
      .from("competitor_prices")
      .insert([{
        product_slug:    row.product_slug,
        competitor_name: row.candidate_name,
        competitor_price: price,
        competitor_url:  url,
      }]);

    if (insertErr) {
      alert("Insert error: " + insertErr.message);
      return;
    }

    const { error: updateErr } = await supabase
      .from("review_queue")
      .update({ status: "resolved" })
      .eq("id", row.id);

    if (updateErr) {
      alert("Couldn’t mark review done: " + updateErr.message);
      return;
    }

    setRows(prev => prev.filter(r => r.id !== row.id));
  }

  // ── Correct: ask for name, price & URL ────────────────────────────────────
  async function handleCorrect(row: ReviewRow) {
    const newName = prompt(
      `Correct shop name (was: ${row.candidate_name}):`
    );
    if (!newName) return;

    const rawPrice = prompt("Enter the correct price:");
    const newPrice = rawPrice ? parseInt(rawPrice, 10) : 0;

    const newUrl = prompt("Enter the correct Torob URL:");

    const { error: corrInsert } = await supabase
      .from("competitor_prices")
      .insert([{
        product_slug:    row.product_slug,
        competitor_name: newName,
        competitor_price: newPrice,
        competitor_url:  newUrl || "",
      }]);

    if (corrInsert) {
      alert("Error inserting corrected data: " + corrInsert.message);
      return;
    }

    const { error: corrUpdate } = await supabase
      .from("review_queue")
      .update({ status: "resolved" })
      .eq("id", row.id);

    if (corrUpdate) {
      alert("Error marking review done: " + corrUpdate.message);
      return;
    }

    setRows(prev => prev.filter(r => r.id !== row.id));
  }
}
