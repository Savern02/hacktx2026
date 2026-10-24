import { Button } from "@/components/ui/button";
import Link from "next/link";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-gray-50 dark:bg-gray-900 p-8">
      <div className="text-center max-w-2xl">
        <h1 className="text-8xl font-bold text-gray-800 dark:text-white mb-8">
          Equa
        </h1>
        <p> **Insert easy to use demo of the project**</p>
        <h1 className="text-4xl font-bold text-gray-800 dark:text-white mb-8">
         Equality Finnances
        </h1>
<h2 className="text-3xl text-gray-800 dark:text-white mb-8">
          Take care of your finnances.
        </h2>
        <div className="flex justify-center gap-4">
          <Link href="/login">
            <Button size="lg">Log in</Button>
          </Link>
          <Link href="/register">
            <Button size="lg" variant="outline">
              Sign up
            </Button>
          </Link>
        </div>
      </div>
    </main>
  );
}
