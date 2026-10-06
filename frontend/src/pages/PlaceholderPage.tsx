import type { User } from "../components/RoleSwitcher.tsx";

type PlaceholderPageProps = {
  title: string;
  me: User | null;
};

export function PlaceholderPage({ title, me }: PlaceholderPageProps) {
  return (
    <main>
      <h1>{title}</h1>
      {me ? (
        <p>
          Signed in as {me.name}, {me.role}
        </p>
      ) : (
        <p>Loading account…</p>
      )}
    </main>
  );
}
