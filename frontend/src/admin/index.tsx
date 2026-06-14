/**
 * Placeholder admin dashboard. Reached only via <AdminRoute> (cosmetic guard);
 * the real dashboard is built out here in a later PR. Server-side
 * @admin_required on /api/admin/* is the actual access boundary.
 */
export default function Admin() {
  return (
    <div className="p-6">
      <h1 className="text-foreground text-2xl font-semibold dark:text-white">
        Admin
      </h1>
      <p className="text-muted-foreground mt-2 text-sm">
        Admin dashboard coming soon.
      </p>
    </div>
  );
}
