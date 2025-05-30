"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

export default function ProductList() {
  const [products, setProducts] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    supabase
      .from("products")
      .select("*")
      .then(({ data, error }) => {
        if (error) setError(error.message);
        else setProducts(data!);
      });
  }, []);

  if (error) return <p>Error: {error}</p>;
  return (
    <ul>
      {products.map((p) => (
        <li key={p.id}>{p.name}: ${p.price}</li>
      ))}
    </ul>
  );
}
