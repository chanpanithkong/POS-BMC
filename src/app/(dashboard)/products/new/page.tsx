"use client";

import { ProductForm } from "@/components/products/product-form";
import { RequirePermission } from "@/components/shared/page";

export default function NewProductPage() {
  return <RequirePermission anyOf={["products.create"]}><ProductForm /></RequirePermission>;
}
