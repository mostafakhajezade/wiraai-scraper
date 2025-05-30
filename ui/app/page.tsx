// app/page.tsx
import { supabase } from "./lib/supabase";

type Product = {
  id: number;
  name: string;
  price: number;
  url: string;
};

type CompetitorPrice = {
  product_slug: string;
  competitor_name: string;
  competitor_price: number;
};

export default async function Page() {
  // 1) Fetch products
  const { data: products, error: prodErr } = await supabase
    .from<Product>("products")
    .select("id, name, price, url");

  // 2) Fetch competitor prices
  const { data: comps, error: compErr } = await supabase
    .from<CompetitorPrice>("competitor_prices")
    .select("product_slug, competitor_name, competitor_price");

  // 3) Error handling
  if (prodErr || compErr) {
    return (
      <main style={{ padding: 20 }}>
        <h1>Products</h1>
        <p style={{ color: "red" }}>
          {prodErr?.message || compErr?.message}
        </p>
      </main>
    );
  }

  // 4) Group competitor prices by product_slug
  const compsBySlug = (comps || []).reduce<Record<string, CompetitorPrice[]>>(
    (acc, c) => {
      acc[c.product_slug] = acc[c.product_slug] || [];
      acc[c.product_slug].push(c);
      return acc;
    },
    {}
  );

  return (
    <main style={{ padding: 20 }}>
      <h1>Products</h1>

      {products && products.length > 0 ? (
        <ul>
          {products.map((p) => {
            // extract slug from URL
            const slug = p.url.split("/product/")[1] || "";
            const cp = compsBySlug[slug] || [];

            return (
              <li key={p.id} style={{ marginBottom: 16 }}>
                <strong>{p.name}</strong> —{" "}
                {p.price.toLocaleString()} تومان

                {cp.length > 0 && (
                  <ul style={{ marginTop: 4, paddingLeft: 20 }}>
                    {cp.map((c) => (
                      <li key={c.competitor_name}>
                        {c.competitor_name}:{" "}
                        {c.competitor_price.toLocaleString()} تومان
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p>No products found.</p>
      )}
    </main>
  );
}
