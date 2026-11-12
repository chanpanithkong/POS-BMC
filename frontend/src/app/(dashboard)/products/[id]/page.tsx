"use client";

import { useParams } from "next/navigation";
import { ProductForm } from "@/components/products/product-form";
import { RequirePermission } from "@/components/shared/page";

export default function ProductDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <RequirePermission anyOf={["products.view"]}><ProductForm key={id} productId={id} /></RequirePermission>;
}
