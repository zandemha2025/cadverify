import Link from "next/link";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard" },
  { href: "/batch", label: "Batch" },
  { href: "/reconstruct", label: "Image to 3D" },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <nav className="mb-8 flex items-center gap-6 border-b pb-4">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="text-sm font-medium text-gray-600 hover:text-gray-900"
          >
            {item.label}
          </Link>
        ))}
      </nav>
      {children}
    </div>
  );
}
