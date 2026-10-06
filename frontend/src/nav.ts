export type NavItem = {
  label: string;
  to: string;
};

const NAV: Record<string, NavItem[]> = {
  provider: [
    { label: "Products", to: "/products" },
    { label: "New order", to: "/orders/new" },
    { label: "Dashboard", to: "/dashboard" },
  ],
  patient: [{ label: "My orders", to: "/patient/orders" }],
  admin: [{ label: "Stock & COGS", to: "/admin/products" }],
};

export function navFor(role: string): NavItem[] {
  return NAV[role] ?? [];
}

export function homeFor(role: string): string {
  return navFor(role)[0]?.to ?? "/";
}
