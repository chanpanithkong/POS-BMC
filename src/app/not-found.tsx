import Link from "next/link";

export default function NotFound() {
  return (
    <main className="grid min-h-svh place-items-center p-6 text-center">
      <div className="space-y-2">
        <p className="text-sm font-medium text-muted-foreground">404</p>
        <h1 className="text-xl font-semibold">Page not found</h1>
        <p className="text-sm text-muted-foreground">This page does not exist or has moved.</p>
        <Link href="/dashboard" className="inline-block text-sm font-medium text-primary hover:underline">Back to dashboard</Link>
      </div>
    </main>
  );
}
