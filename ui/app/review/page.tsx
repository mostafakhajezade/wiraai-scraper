// ui/app/review/page.tsx
"use client"; // This page uses client-side hooks for interactive forms

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabaseClient";

type ReviewRow = {
  id: string;
  product_slug: string;
  candidate_name: string;
  candidate_shop: string;
  fuzzy_score: number;
  semantic_score: number;
  raw_torob_data: any;
  status: string;
  created_at: string;
};

export default function ReviewPage() {
  const [rows, setRows] = useState<ReviewRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch pending review_queue items
  useEffect(() => {
    async function fetchQueue() {
      setLoading(true);
      const { data, error } = await supabase
        .from("review_queue")
        .select("*")
        .eq("status", "pending"); // or remove .eq(...) if you don’t have status
      if (error) {
        setError(error.message);
      } else {
        setRows(data || []);
      }
      setLoading(false);
    }
    fetchQueue();
  }, []);

  if (loading) return <p className="p-4">Loading…</p>;
  if (error) return <p className="p-4 text-red-600">Error: {error}</p>;

  return (
    <main className="p-4">
      <h1 className="text-2xl font-semibold mb-4">Review Queue</h1>
      {rows.length === 0 ? (
        <p>No items to review!</p>
      ) : (
        <ul className="space-y-4">
          {rows.map((row) => (
            <li key={row.id} className="border rounded-lg p-4">
              <p>
                <strong>Product slug:</strong> {row.product_slug}
              </p>
              <p>
                <strong>Proposed name:</strong> {row.candidate_name} (
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
      )}
    </main>
  );

  // ── Approve handler ───────────────────────────────────────────────────────
  async function handleApprove(row: ReviewRow) {
    // 1) Insert into competitor_prices
    const { error: insertError } = await supabase
      .from("competitor_prices")
      .insert([
        {
          product_slug: row.product_slug,
          competitor_name: row.candidate_name,
          competitor_price: (row as any).price ?? 0, // if your raw_torob_data includes price
        },
      ]);
    if (insertError) {
      alert("Error inserting competitor price: " + insertError.message);
      return;
    }

    // 2) Mark review_queue row as “resolved”
    const { error: updateError } = await supabase
      .from("review_queue")
      .update({ status: "resolved" })
      .eq("id", row.id);
    if (updateError) {
      alert("Error updating review status: " + updateError.message);
      return;
    }

    // 3) Locally remove it from state
    setRows((prev) => prev.filter((r) => r.id !== row.id));
  }

  // ── Correct handler ────────────────────────────────────────────────────────
  async function handleCorrect(row: ReviewRow) {
    const correctedName = prompt(
      `Enter the correct shop name (was: ${row.candidate_name}):`
    );
    if (!correctedName) return; // do nothing if canceled

    // 1) Insert the corrected row into competitor_prices
    const { error: corrInsertError } = await supabase
      .from("competitor_prices")
      .insert([
        {
          product_slug: row.product_slug,
          competitor_name: correctedName,
          competitor_price: 0, // or ask user for price
        },
      ]);
    if (corrInsertError) {
      alert("Error inserting corrected competitor price: " + corrInsertError.message);
      return;
    }

    // 2) Update review_queue → resolved
    const { error: corrUpdateError } = await supabase
      .from("review_queue")
      .update({ status: "resolved" })
      .eq("id", row.id);
    if (corrUpdateError) {
      alert("Error updating review status: " + corrUpdateError.message);
      return;
    }

    setRows((prev) => prev.filter((r) => r.id !== row.id));
  }
}
