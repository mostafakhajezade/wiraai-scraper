// app/review/page.tsx
"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";

export default function ReviewPage() {
  const [items, setItems] = useState<any[]>([]);
  useEffect(() => {
    supabase
      .from("competitor_prices")
      .select("*")
      .then(({ data }) => setItems(data ?? []));
  }, []);

  return (
    <main style={{ padding: 20 }}>
      <h1>Review Competitor Prices</h1>
      <ul>
        {items.map((row) => (
          <li key={`${row.product_slug}-${row.competitor_name}`}>
            {row.product_slug}: {row.competitor_name} — {row.competitor_price}
          </li>
        ))}
      </ul>
    </main>
  );
}
