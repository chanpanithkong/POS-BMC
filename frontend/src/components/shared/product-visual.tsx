import { createElement } from "react";
import { Apple, Boxes, Cookie, CupSoda, Gift, Milk, type LucideIcon, Shirt, ShoppingBasket, Sparkles, SprayCan } from "lucide-react";
import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  "cup-soda": CupSoda,
  cookie: Cookie,
  "shopping-basket": ShoppingBasket,
  milk: Milk,
  apple: Apple,
  "spray-can": SprayCan,
  sparkles: Sparkles,
  shirt: Shirt,
  gift: Gift,
};

export function categoryIcon(key: string | undefined): LucideIcon {
  return (key && ICONS[key]) || Boxes;
}

/** Shows the uploaded product image, or a neutral category tile when there is none. */
export function ProductVisual({ image, icon, name, className }: { image: string | null; icon?: string; name: string; className?: string }) {
  if (image) {
    // Images are local data URLs chosen by the user, so next/image optimisation does not apply.
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={image} alt={name} className={cn("rounded-md object-cover", className)} />;
  }
  return (
    <div className={cn("grid place-items-center rounded-md bg-muted text-muted-foreground", className)} aria-hidden>
      {createElement(categoryIcon(icon), { className: "size-1/2 max-h-8 max-w-8", strokeWidth: 1.5 })}
    </div>
  );
}
