import { redirect } from "next/navigation";

/**
 * Root page: server-side redirect based on setup status.
 * In the browser the client-side nav handles the redirect via the
 * setup wizard guard, but this covers direct URL loads.
 */
export default function HomePage() {
  // Default to /dashboard; the layout guard redirects to /setup if needed.
  redirect("/dashboard");
}
