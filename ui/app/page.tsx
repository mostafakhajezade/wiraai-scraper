// ui/app/page.tsx
import { supabase } from "@/lib/supabaseClient";

export default async function Page() {
  // Fetch all products
  const { data: products, error } = await supabase
    .from("products")
    .select("id, name, price");

  if (error) {
    return (
      <main className="p-4">
        <h1>Products</h1>
        <p className="text-red-600">Error: {error.message}</p>
      </main>
    );
  }

  return (
    <main className="p-4">
      <h1 className="text-2xl font-semibold mb-4">All Products</h1>
      {products && products.length > 0 ? (
        <ul className="space-y-2">
          {products.map((p) => (
            <li key={p.id} className="border p-2 rounded">
              {p.name} — {p.price.toLocaleString()} تومان
            </li>
          ))}
        </ul>
      ) : (
        <p>No products found.</p>
      )}
      <a
        href="/review"
        className="mt-6 inline-block px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
      >
        Go to Review Queue
      </a>
    </main>
  );
}
