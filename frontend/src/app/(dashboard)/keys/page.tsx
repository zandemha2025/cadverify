import { RevealOnceModal } from "@/components/RevealOnceModal";
import { createKey, listKeys, revokeKey, rotateKey } from "./actions";

type KeyRow = {
  id: number;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

export default async function KeysPage() {
  const keys = (await listKeys()) as KeyRow[];
  return (
    <main className="space-y-6">
      <RevealOnceModal />
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">API keys</h1>
        <form
          action={async () => {
            "use server";
            await createKey("Default");
          }}
        >
          <button className="rounded-md bg-black px-3 py-1 text-white text-sm">
            Create key
          </button>
        </form>
      </div>
      <ul className="divide-y rounded-md border">
        {keys.map((k) => (
          <li
            key={k.id}
            className="flex items-center justify-between p-3 text-sm"
          >
            <div>
              <div className="font-medium">{k.name}</div>
              <div className="text-neutral-500">
                cv_live_{k.prefix}_…  ·  last used {k.last_used_at ?? "never"}
                {k.revoked_at ? " · revoked" : ""}
              </div>
            </div>
            <div className="flex gap-2">
              <form
                action={async () => {
                  "use server";
                  await rotateKey(k.id);
                }}
              >
                <button className="rounded border px-2 py-0.5">Rotate</button>
              </form>
              <form
                action={async () => {
                  "use server";
                  await revokeKey(k.id);
                }}
              >
                <button className="rounded border px-2 py-0.5 text-red-600">
                  Revoke
                </button>
              </form>
            </div>
          </li>
        ))}
      </ul>
    </main>
  );
}
