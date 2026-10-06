import { useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router";

import { ApiError, apiGet } from "./api/client.ts";
import { RoleSwitcher, type User } from "./components/RoleSwitcher.tsx";
import { homeFor, navFor } from "./nav.ts";
import { NewOrderPage } from "./pages/NewOrderPage.tsx";
import { PatientOrderRoute } from "./pages/PatientOrderPage.tsx";
import { PatientOrdersPage } from "./pages/PatientOrdersPage.tsx";
import { PlaceholderPage } from "./pages/PlaceholderPage.tsx";
import { ProductsPage } from "./pages/ProductsPage.tsx";

const STORAGE_KEY = "cerbo.userId";

function chosenUserId(users: User[]): number {
  const raw = localStorage.getItem(STORAGE_KEY);
  const stored = raw !== null && /^\d+$/.test(raw) ? Number(raw) : null;
  if (stored !== null && users.some((user) => user.id === stored)) {
    return stored;
  }
  const first = users[0];
  if (first === undefined) {
    throw new Error("No users");
  }
  return first.id;
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.code}: ${error.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed";
}

export default function App() {
  const [users, setUsers] = useState<User[] | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [me, setMe] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    apiGet<User[]>("/users", null)
      .then((listed) => {
        if (cancelled) {
          return;
        }
        const id = chosenUserId(listed);
        localStorage.setItem(STORAGE_KEY, String(id));
        setError(null);
        setUsers(listed);
        setUserId(id);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(errorText(cause));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (userId === null) {
      return;
    }
    let cancelled = false;
    apiGet<User>("/me", userId)
      .then((current) => {
        if (!cancelled) {
          setMe(current);
          setError(null);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(errorText(cause));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  function selectUser(nextId: number) {
    const next = users?.find((user) => user.id === nextId);
    const previous = users?.find((user) => user.id === userId);
    setError(null);
    setMe(null);
    setUserId(nextId);
    localStorage.setItem(STORAGE_KEY, String(nextId));
    const roleChanged = next !== undefined && previous !== undefined && next.role !== previous.role;
    if (roleChanged && !navFor(next.role).some((item) => item.to === location.pathname)) {
      navigate(homeFor(next.role));
    }
  }

  const links = me === null ? [] : navFor(me.role);

  return (
    <>
      <header className="container app-header">
        <strong>Cerbo supplement ordering</strong>
        {users !== null && userId !== null ? (
          <RoleSwitcher users={users} userId={userId} onChange={selectUser} />
        ) : null}
        {me !== null ? (
          <p>
            Signed in as {me.name}, {me.role}
          </p>
        ) : null}
        <nav className="app-nav" aria-label="Primary">
          {links.map((item) => (
            <NavLink key={item.to} to={item.to}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        {error !== null ? <p role="alert">{error}</p> : null}
      </header>
      <div className="container">
        <Routes>
          <Route path="/" element={<Home me={me} />} />
          <Route
            path="/products"
            element={me !== null ? <ProductsPage userId={me.id} /> : <p>Loading account…</p>}
          />
          <Route
            path="/orders/new"
            element={
              me !== null ? <NewOrderPage key={me.id} userId={me.id} /> : <p>Loading account…</p>
            }
          />
          <Route path="/dashboard" element={<PlaceholderPage title="Dashboard" me={me} />} />
          <Route
            path="/patient/orders"
            element={
              me !== null ? (
                <PatientOrdersPage key={me.id} userId={me.id} />
              ) : (
                <p>Loading account…</p>
              )
            }
          />
          <Route
            path="/orders/:orderId"
            element={
              me !== null ? (
                <PatientOrderRoute key={me.id} userId={me.id} role={me.role} />
              ) : (
                <p>Loading account…</p>
              )
            }
          />
          <Route
            path="/admin/products"
            element={<PlaceholderPage title="Stock & COGS" me={me} />}
          />
        </Routes>
      </div>
    </>
  );
}

function Home({ me }: { me: User | null }) {
  if (me === null) {
    return <p>Loading account…</p>;
  }
  return <Navigate to={homeFor(me.role)} replace />;
}
