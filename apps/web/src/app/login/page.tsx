import { LoginForm } from "@/components/LoginForm";
import { isAuthenticated } from "@/lib/auth";
import { redirect } from "next/navigation";

export default async function LoginPage() {
  if (await isAuthenticated()) redirect("/series");
  return (
    <main className="mx-auto flex min-h-screen max-w-lg items-center px-6 py-16">
      <LoginForm />
    </main>
  );
}

