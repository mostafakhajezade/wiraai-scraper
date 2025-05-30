// app/page.tsx
import { supabase } from "./lib/supabase";

export default async function Page() {
  const { data: products, error } = await supabase
    .from("products")
    .select("id, name, price");

  return (
    <main style={{ padding: 20 }}>
      <h1>Products</h1>
      {error
        ? <p style={{ color: "red" }}>Error: {error.message}</p>
        : products && products.length > 0
          ? <ul>
              {products.map(p =>
                <li key={p.id}>{p.name} — {p.price.toLocaleString()} تومان</li>
              )}
            </ul>
          : <p>No products found.</p>
      }
    </main>
  );
}
